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
import { Section } from "../../ui/Section";
import { Tabs, TabPanel, type Tab } from "../../ui/Tabs";
import { Button } from "../../ui/Button";
import { Feedback, Message } from "../../ui/Feedback";
import type { ProjectLink } from "../guided/workspace/model";
import { ModelMenu } from "../settings/ModelMenu";
import { useProjectOptions } from "./useProjectOptions";
import { ContextPanel } from "./ContextPanel";
import { JobStatus } from "../../ui/JobStatus";
import { ImageManager } from "../images/ImageManager";
import { ImageTextEditor } from "../images/ImageTextEditor";
import { AssistantTask } from "../../ui/AssistantTask";
import { StatusMark } from "../../ui/StatusMark";
import { StatusIcon } from "../../ui/StatusIcon";
import { displayLabels, displayMarks } from "../../ui/displayStatus";
import { HelpPopover } from "../../ui/HelpPopover";

export type TranslationView = "progress" | "context" | "images";
type View = TranslationView;
const labels: Record<string, string> = {
  preparation: "Preparation",
  extraction: "Extraction",
  translation: "Translation",
  injection: "Injection",
  qa: "QA",
  patch: "Patch",
};

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
  const copy = () =>
    action.run(
      async () => {
        await flushDrafts();
        if (draft.dirty) await draft.save();
        const result = await api.translation.prepare(project.id);
        await window.dazedtl.copyText(result.handoff);
      },
      "Starting prompt copied. Paste it into your coding assistant to begin or resume.",
      "copy",
    );
  // The page's main action ends every tab's footer.
  const copyControl = (variant: "primary" | "default" = "primary") => (
    <ActionControl
      variant={variant}
      label={
        draft.dirty ? "Save and copy starting prompt" : "Copy starting prompt"
      }
      disabled={disabled}
      pending={action.busy && action.key === "copy"}
      pendingText="Copying…"
      error={action.key === "copy" ? action.error : ""}
      notice={action.key === "copy" ? action.notice : ""}
      onClick={() => void copy()}
    />
  );
  const saveOptions = () =>
    void action.run(draft.save, "Project options saved.");
  const progressBody = useRef<HTMLDivElement>(null);
  useShortcut(
    saveKey,
    draft.dirty && !action.busy ? saveOptions : null,
    progressBody,
    { inFields: true },
  );
  const progress = state.progress;
  const text = progress?.metrics.text;
  const images = progress?.metrics.images;
  const latest = state.jobs[0];
  return (
    <PageLayout
      variant="editor"
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
          onChange={(next) =>
            action.run(async () => {
              await flushDrafts();
              setView(next);
            })
          }
        />
      </div>
      <Message
        message={action.key === "copy" ? "" : action.error}
        onDismiss={action.clear}
      />
      {[...state.warnings, ...(progress?.warnings || [])].map((warning) => (
        <p className="banner" key={warning}>
          {warning}
        </p>
      ))}
      <TabPanel id="translation" value={view}>
        {view === "progress" && (
          <>
            <PageBody ref={progressBody}>
              <Section
                title={
                  <>
                    Translation approach{" "}
                    <HelpPopover label="Translation approach">
                      The starting prompt handles engine investigation, setup,
                      translation and delivery. The app tracks saved work in
                      every mode.
                    </HelpPopover>
                  </>
                }
              >
                <fieldset disabled={disabled}>
                  <label>
                    Translation mode
                    <select
                      value={draft.value.options.mode}
                      onChange={(event) =>
                        edit(
                          "mode",
                          event.target.value as TranslationOptions["mode"],
                        )
                      }
                    >
                      <option value="agent">Agent Translation</option>
                      <option value="live">Live API Translation</option>
                      <option value="batch">API Batch Translation</option>
                    </select>
                  </label>
                  {draft.value.options.mode !== "agent" && (
                    <div className="translation-connection">
                      <dl
                        className="translation-facts"
                        aria-label="Current API selection"
                      >
                        <div>
                          <dt>Connection</dt>
                          <dd>{state.connection?.name || "Not selected"}</dd>
                        </div>
                        <div>
                          <dt>Model</dt>
                          <dd>
                            <ModelMenu
                              model={state.connection?.model || ""}
                              connection={state.connection?.name || ""}
                              disabled={disabled}
                              manage={settings}
                            />
                          </dd>
                        </div>
                      </dl>
                    </div>
                  )}
                  <label>
                    Instructions for the translation agent
                    <textarea
                      rows={4}
                      value={draft.value.options.instructions}
                      placeholder="Game-specific requirements, reference games, or a narrower task…"
                      onChange={(event) =>
                        edit("instructions", event.target.value)
                      }
                    />
                  </label>
                  <div className="translation-options">
                    <label className="translation-check">
                      <input
                        type="checkbox"
                        checked={draft.value.options.include_images}
                        onChange={(event) =>
                          edit("include_images", event.target.checked)
                        }
                      />
                      Include image text
                    </label>
                    <label className="translation-check">
                      <input
                        type="checkbox"
                        checked={draft.value.options.include_glossary_base}
                        onChange={(event) =>
                          edit("include_glossary_base", event.target.checked)
                        }
                      />
                      Include base glossary
                    </label>
                    {project.engine === "MVMZ" && (
                      <label className="translation-check">
                        <input
                          type="checkbox"
                          checked={draft.value.options.install_forge}
                          onChange={(event) =>
                            edit("install_forge", event.target.checked)
                          }
                        />
                        Install Forge for playtesting
                      </label>
                    )}
                  </div>
                </fieldset>
              </Section>
              <AssistantTask
                state={
                  progress?.blocker
                    ? "blocked"
                    : progress?.updated_at
                      ? Object.values(progress.phases).every((phase) =>
                          ["complete", "out_of_scope"].includes(phase),
                        )
                        ? "done"
                        : "waiting"
                      : "not_started"
                }
                progress={
                  progress?.updated_at
                    ? "last report " +
                      new Date(progress.updated_at).toLocaleString()
                    : undefined
                }
                description={
                  progress?.blocker ||
                  progress?.next_action ||
                  "Your assistant backs up the game, saves its version and prepares shared guidance, then translates; its saved reports appear here."
                }
                help="These are saved reports. An assistant's last report does not show that its session is still running, and text completion does not establish runtime QA completion."
              >
                <div className="translation-phases">
                  {Object.entries(labels).map(([key, label]) => {
                    const phase = progress?.phases[key] || "pending";
                    return (
                      <div key={key} data-state={phase}>
                        <span>{label}</span>
                        {/* The assistant reports a phase as active; the
                            app does not claim it is running. */}
                        <strong>
                          <StatusMark
                            state={
                              phase === "complete"
                                ? "done"
                                : phase === "active"
                                  ? "waiting"
                                  : phase === "blocked"
                                    ? "blocked"
                                    : phase === "out_of_scope"
                                      ? "skipped"
                                      : "not_started"
                            }
                          />
                        </strong>
                      </div>
                    );
                  })}
                </div>
                {!!(text?.translated || text?.reviewed) && (
                  <div className="translation-metrics">
                    <p>
                      <strong>{text.translated.toLocaleString()}</strong>{" "}
                      translated /{" "}
                      {text.total === null
                        ? text.discovered === undefined
                          ? "unknown total"
                          : text.discovered.toLocaleString() + " discovered"
                        : text.total.toLocaleString()}{" "}
                      units
                    </p>
                    {!!text.reviewed && (
                      <p>
                        <strong>{text.reviewed.toLocaleString()}</strong>{" "}
                        source-checked
                      </p>
                    )}
                    <p>
                      {text.total === null
                        ? "Full coverage has not yet been audited."
                        : "Source inventory reported complete."}
                    </p>
                  </div>
                )}
                {state.options.include_images && !!images?.translated && (
                  <p>
                    Images: {images.translated} translated /{" "}
                    {images.total ?? "unknown total"}
                  </p>
                )}
              </AssistantTask>
              {latest && latest.status !== "complete" && (
                <Section title="App operation">
                  <JobStatus job={latest} />
                  {latest.kind === "translation" && !!latest.units && (
                    <p>
                      {latest.accepted_units} / {latest.units} units saved
                    </p>
                  )}
                  {["running", "waiting"].includes(latest.status) && (
                    <Button
                      disabled={action.busy || latest.stop_requested}
                      onClick={() =>
                        action.run(() =>
                          api.translation.stop(project.id, latest.id),
                        )
                      }
                    >
                      Pause at the next safe point
                    </Button>
                  )}
                </Section>
              )}
              <Section title="Setup">
                <dl className="translation-facts">
                  <div>
                    <dt>Original backup</dt>
                    <dd>
                      {state.lifecycle.source_backup?.available === false
                        ? "Unavailable"
                        : state.lifecycle.source_backup
                          ? "Saved"
                          : "Pending"}
                    </dd>
                  </div>
                  <div>
                    <dt>Version history</dt>
                    <dd>{state.git?.configured ? "Set up" : "Pending"}</dd>
                  </div>
                  <div>
                    <dt>Game version</dt>
                    <dd>{state.git?.original_version || "Not recorded"}</dd>
                  </div>
                  <div>
                    <dt>Translation version</dt>
                    <dd>{state.git?.translation_commit ? "Saved" : "None"}</dd>
                  </div>
                </dl>
                <div className="lens-project-links">
                  <Button variant="link" onClick={() => openProject("backups")}>
                    Backups & recovery
                  </Button>
                  <Button
                    variant="link"
                    onClick={() => openProject("versions")}
                  >
                    Game updates
                  </Button>
                </div>
              </Section>
              {state.statusText && (
                <details>
                  <summary>Detailed agent report</summary>
                  <pre className="translation-report">{state.statusText}</pre>
                </details>
              )}
              {state.handoff && (
                <details>
                  <summary>Starting / resume prompt</summary>
                  <pre className="translation-report">{state.handoff}</pre>
                </details>
              )}
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
