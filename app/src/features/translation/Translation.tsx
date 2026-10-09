import { useRef, useState } from "react";
import { FolderOpen } from "lucide-react";
import { api } from "../../api/client";
import type {
  Project,
  TranslationOptions,
  TranslationState,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import {
  saveKey,
  shortcutKeys,
  shortcutLabel,
  useShortcut,
} from "../../state/useShortcut";
import { PageLayout, PageHeader, PageBody } from "../../ui/PageLayout";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Tabs, TabPanel, type Tab } from "../../ui/Tabs";
import { Button } from "../../ui/Button";
import { Feedback, Message } from "../../ui/Feedback";
import type { ProjectLink } from "../guided/workspace/model";
import { useProjectOptions } from "./useProjectOptions";
import { ContextPanel } from "./ContextPanel";
import { OptionsPanel } from "./OptionsPanel";
import {
  attemptJobs,
  awaitingQuote,
  estimateOutdated,
  latestApiRun,
} from "./apiRun";
import { ProgressPanel } from "./ProgressPanel";
import { ImageManager } from "../images/ImageManager";
import { ImageTextEditor } from "../images/ImageTextEditor";
import { StatusIcon } from "../../ui/StatusIcon";
import { displayLabels, displayMarks } from "../../ui/displayStatus";

export type TranslationView = "progress" | "options" | "context" | "images";
type View = TranslationView;

export default function Translation({
  project,
  settings,
  openProject,
  view,
}: {
  project: Project;
  settings: () => void;
  /** History, game updates and backups live on the Project page. */
  openProject: ProjectLink;
  /** The tab to open on, such as Images for a copied image task. */
  view?: View;
}) {
  const application = useApplication();
  const state = application.snapshot?.translation;
  if (!state || state.projectId !== project.id)
    return (
      <PageLayout>
        <PageHeader title="Assistant-led" />
        <Message
          message={
            application.snapshot?.translationError ||
            "The project folder is unavailable."
          }
        />
      </PageLayout>
    );
  return (
    <Workspace
      project={project}
      state={state}
      settings={settings}
      openProject={openProject}
      initialView={view}
    />
  );
}

function Workspace({
  project,
  state,
  settings,
  openProject,
  initialView = "progress",
}: {
  project: Project;
  state: TranslationState;
  settings: () => void;
  openProject: ProjectLink;
  initialView?: View;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const draft = useProjectOptions(state, action.report);
  const [view, setView] = useState<View>(initialView);
  const [editorAssets, setEditorAssets] = useState<string[] | null>(null);
  const [imageFooter, setImageFooter] = useState<HTMLDivElement | null>(null);
  const tabs: Tab<View>[] = [
    { id: "progress", label: "Progress" },
    { id: "options", label: "Options" },
    { id: "context", label: "Context" },
    {
      id: "images",
      label: "Images",
      // Image work another project saved here waits for a choice.
      status: application.snapshot?.imagesForeign && (
        <StatusIcon
          status={displayMarks.needs_review}
          label={displayLabels.needs_review}
          size={14}
        />
      ),
    },
  ];
  const disabled = state.active || action.busy || draft.committing;
  const edit = <K extends keyof TranslationOptions>(
    key: K,
    value: TranslationOptions[K],
  ) =>
    draft.session.edit((current) => ({
      ...current,
      options: { ...current.options, [key]: value },
    }));
  const show = (next: View) =>
    action.run(async () => {
      await flushDrafts();
      setView(next);
    });
  const copy = (key: string) =>
    action.run(
      async () => {
        await flushDrafts();
        if (draft.dirty) await draft.save();
        const result = await api.translation.prepare(project.id);
        await window.dazedtl.copyText(result.handoff);
      },
      "Starting prompt copied. Paste it into your coding assistant to begin or resume.",
      key,
    );
  // The same prompt starts and resumes; once the assistant has reported,
  // copying it again resumes the saved work.
  const started = !!state.progress?.updated_at;
  // An API run can wait hours at the provider, and the prompt hands its
  // results back to the assistant; only an operation changing the game holds
  // the prompt.
  const operating = state.jobs.some(
    (job) =>
      job.kind === "operation" && ["running", "waiting"].includes(job.status),
  );
  const copyDisabled = operating || action.busy || draft.committing;
  const run = latestApiRun(attemptJobs(state));
  // The page's main action ends every tab's footer. A second copy, such as
  // the API run's reminder, reports under its own key beside itself.
  const copyControl = (
    variant: "primary" | "default" = "primary",
    key = "copy",
  ) => (
    <ActionControl
      variant={variant}
      label={
        (draft.dirty ? "Save and copy" : "Copy") +
        (started ? " prompt to resume" : " starting prompt")
      }
      disabled={copyDisabled}
      pending={action.busy && action.key === key}
      pendingText="Copying…"
      error={action.key === key ? action.error : ""}
      notice={action.key === key ? action.notice : ""}
      onClick={() => void copy(key)}
    />
  );
  const saveOptions = () =>
    void action.run(draft.save, "Project options saved.");
  const optionsBody = useRef<HTMLDivElement>(null);
  useShortcut(
    saveKey,
    draft.dirty && !action.busy ? saveOptions : null,
    optionsBody,
    { inFields: true },
  );
  return (
    <PageLayout
      variant="editor"
      wide={view === "images"}
      className="lens-method"
      aria-label="Assistant-led workspace"
    >
      <PageHeader
        title="Assistant-led"
        actions={
          // The workspace folder exists once the assistant sets it up.
          state.initialized && (
            <div className="actions">
              <Button
                disabled={action.busy}
                onClick={() =>
                  action.run(() =>
                    window.dazedtl.openFolder("projectWorkspace"),
                  )
                }
              >
                <FolderOpen size={16} />
                Open workspace folder
              </Button>
            </div>
          )
        }
      />
      <div className="frame-row">
        <Tabs
          id="translation"
          label="Assistant-led sections"
          items={tabs}
          value={view}
          disabled={action.busy}
          onChange={(next) => void show(next)}
        />
      </div>
      <Message
        message={
          ["copy", "resume", "approve", "pause"].includes(action.key)
            ? ""
            : action.error
        }
        onDismiss={action.clear}
      />
      {[...state.warnings, ...(state.progress?.warnings || [])].map(
        (warning) => (
          <p className="banner" key={warning}>
            {warning}
          </p>
        ),
      )}
      <TabPanel id="translation" value={view}>
        {view === "progress" && (
          <>
            <PageBody>
              <ProgressPanel
                state={state}
                options={draft.value.options}
                action={action}
                openProject={openProject}
                showOptions={() => void show("options")}
                resume={copyControl("default", "resume")}
              />
            </PageBody>
            <ActionBar feedback={<Feedback dirty={draft.dirty} />}>
              {/* An estimate the user can approve holds the one primary. */}
              {copyControl(
                awaitingQuote(run) && !estimateOutdated(run)
                  ? "default"
                  : "primary",
              )}
            </ActionBar>
          </>
        )}
        {view === "options" && (
          <>
            <PageBody ref={optionsBody}>
              <OptionsPanel
                project={project}
                state={state}
                options={draft.value.options}
                edit={edit}
                disabled={disabled}
                settings={settings}
              />
            </PageBody>
            <ActionBar feedback={<Feedback dirty={draft.dirty} />}>
              {draft.dirty && (
                <>
                  <Button
                    disabled={action.busy}
                    onClick={() => action.run(draft.discard)}
                  >
                    Discard draft
                  </Button>
                  <Button
                    title={`Save project options (${shortcutLabel.save})`}
                    aria-keyshortcuts={shortcutKeys.save}
                    disabled={action.busy}
                    onClick={saveOptions}
                  >
                    Save project options
                  </Button>
                </>
              )}
              {copyControl()}
            </ActionBar>
          </>
        )}
        {view === "context" && (
          <ContextPanel state={state} copy={copyControl} />
        )}
        {view === "images" && (
          <>
            <PageBody className="image-task-body">
              <ImageManager
                key={project.id}
                projectId={project.id}
                observed={application.snapshot?.images}
                foreign={application.snapshot?.imagesForeign}
                footer={{
                  target: imageFooter,
                  next: (variant) =>
                    copyControl(variant === "primary" ? "primary" : "default"),
                }}
                onOpenEditor={setEditorAssets}
              />
            </PageBody>
            <div className="footer-slot" ref={setImageFooter} />
          </>
        )}
      </TabPanel>
      {editorAssets && (
        <ImageTextEditor
          projectId={project.id}
          assetIds={editorAssets}
          observationKey={application.snapshot}
          onClose={() => setEditorAssets(null)}
        />
      )}
    </PageLayout>
  );
}
