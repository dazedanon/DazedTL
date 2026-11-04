import { useRef, useState } from "react";
import { api } from "../../api/client";
import type {
  ManualLoad,
  Project,
  TranslationOptions,
  TranslationState,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { flushDrafts } from "../../state/leaveGuards";
import { useAction } from "../../state/useAction";
import { useMinute } from "../../state/useMinute";
import {
  saveKey,
  shortcutKeys,
  shortcutLabel,
  useShortcut,
} from "../../state/useShortcut";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { Feedback, Message } from "../../ui/Feedback";
import { CheckGroup } from "../../ui/FieldRow";
import { FileName } from "../../ui/FileName";
import { FeedbackOwners } from "../../ui/FeedbackOwners";
import { HelpPopover } from "../../ui/HelpPopover";
import { GameWarnings, Notice } from "../../ui/Notice";
import {
  PageBody,
  PageHeader,
  PageLayout,
  PageMessages,
} from "../../ui/PageLayout";
import { StatusPanel } from "../../ui/StatusPanel";
import { TabPanel, Tabs, type Tab } from "../../ui/Tabs";
import { plural, timeAgo, unavailableReason } from "../../ui/displayText";
import { GameLanguagesRow } from "../project/GameLanguages";
import { ImportSummary, exportTranslation } from "../project/TranslationFile";
import type { SettingsSection } from "../settings/Settings";
import {
  attemptJobs,
  awaitingQuote,
  estimateOutdated,
  latestApiRun,
} from "./apiRun";
import { ContextPanel } from "./ContextPanel";
import {
  BaseGlossaryField,
  GameUpdateConfig,
  GameUpdateField,
  TranslationModeField,
} from "./OptionsPanel";
import { ApiRun } from "./ProgressPanel";
import { runnableMode } from "./runnableMode";
import { useProjectOptions } from "./useProjectOptions";

type View = "text" | "options" | "context" | "progress";

const tabs: Tab<View>[] = [
  { id: "text", label: "Text" },
  { id: "options", label: "Options" },
  { id: "context", label: "Context" },
  { id: "progress", label: "Progress" },
];

/**
 * Manual: the user's own tools extract the game's text into a translation
 * file and write the translations back; this page loads the file, estimates
 * and runs its translation, and exports the translations.
 */
export default function ManualTranslation({
  project,
  settings,
}: {
  project: Project;
  settings: (section?: SettingsSection) => void;
}) {
  const application = useApplication();
  const state = application.snapshot?.translation;
  if (!state || state.projectId !== project.id)
    return (
      <PageLayout>
        <PageHeader title="Manual" />
        <Message
          message={
            application.snapshot?.translationError ||
            (project.available === false && unavailableReason(project)) ||
            "The project folder is unavailable."
          }
        />
      </PageLayout>
    );
  return (
    <FeedbackOwners key={project.id}>
      <Workspace project={project} state={state} settings={settings} />
    </FeedbackOwners>
  );
}

function Workspace({
  project,
  state,
  settings,
}: {
  project: Project;
  state: TranslationState;
  settings: (section?: SettingsSection) => void;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const now = useMinute();
  const draft = useProjectOptions(state, action.report);
  // Manual has no Assistant only: a mode Assistant-led saved reads as Batch,
  // and a Batch the connection cannot run as Live.
  const saved = draft.value.options.mode;
  const options: TranslationOptions = {
    ...draft.value.options,
    mode: runnableMode(
      saved === "agent" ? "batch" : saved,
      state.batchUnavailable,
      "live",
    ),
  };
  const loaded = state.manual?.loaded ?? null;
  const [view, setView] = useState<View>(loaded ? "progress" : "text");
  const [load, setLoad] = useState<ManualLoad | null>(null);
  const attempt = attemptJobs(state);
  const run = latestApiRun(attempt);
  // The estimate being prepared, or the last one if it failed.
  const latest = attempt.find(
    (job) => job.kind === "operation" && job.action === "organize",
  );
  const preparing = latest?.status === "complete" ? undefined : latest;
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
  const next = (to: View, variant: "primary" | "default" = "primary") => (
    <Button
      variant={variant}
      disabled={action.busy}
      onClick={() => void show(to)}
    >
      Continue
    </Button>
  );
  const choose = async (path: string | null, key = "load") => {
    const done = await action.run(
      async () => {
        const chosen = path ?? (await window.dazedtl.chooseTranslationFile());
        if (!chosen) return null;
        const result = await api.translation.manualLoad(project.id, chosen);
        setLoad(result);
        return result;
      },
      "",
      key,
    );
    if (done.ok && done.value)
      action.succeed(`Loaded ${plural(done.value.loaded.lines, "line")}.`, key);
  };
  const saveOptions = () =>
    void action.run(draft.save, "Project options saved.");
  const optionsBody = useRef<HTMLDivElement>(null);
  useShortcut(
    saveKey,
    draft.dirty && !action.busy ? saveOptions : null,
    optionsBody,
    { inFields: true },
  );
  const quote = awaitingQuote(run);
  const outdated = estimateOutdated(run);
  const finished = run?.status === "complete";
  const working = !!run && ["running", "waiting"].includes(run.status);
  // A paused or interrupted run resumes: estimating again would send the
  // lines it still holds a second time. One whose requests may have reached
  // the provider is checked in History first.
  const resumable =
    !!run?.approved &&
    ["stopped", "interrupted", "canceled"].includes(run.status);
  const unsure = run?.status === "uncertain";
  const contextDraft = Object.keys(state.drafts.documents).length > 0;
  // An estimate is the next step until one waits, runs or has finished.
  const estimateNext =
    !!loaded &&
    !finished &&
    !working &&
    !resumable &&
    !unsure &&
    (!quote || outdated);
  const estimateBlocked = !loaded
    ? "Load your text file first."
    : state.active
      ? "Wait for the current work to finish."
      : resumable
        ? "Resume the run first, so its lines aren't sent twice."
        : unsure
          ? "Check the run under History on the Project page first."
          : contextDraft
            ? "Save or discard your changes on Context first."
            : "";
  const estimate = (
    <ActionControl
      label={run ? "Estimate again" : "Estimate cost"}
      variant={estimateNext ? "primary" : "default"}
      disabled={disabled || !!estimateBlocked}
      disabledReason={estimateBlocked}
      pending={action.busy && action.key === "estimate"}
      pendingText="Estimating…"
      error={action.key === "estimate" ? action.error : ""}
      feedbackKey="estimate"
      job={preparing}
      onClick={() =>
        void action.run(
          async () => {
            await flushDrafts();
            if (draft.dirty) await draft.save();
            await api.translation.manualEstimate(project.id);
          },
          "",
          "estimate",
        )
      }
    />
  );
  const resume = resumable && run && (
    <ActionControl
      variant="primary"
      label="Resume"
      disabled={disabled}
      disabledReason={
        state.active ? "Wait for the current work to finish." : ""
      }
      pending={action.busy && action.key === "resume"}
      pendingText="Resuming…"
      error={action.key === "resume" ? action.error : ""}
      onClick={() =>
        void action.run(
          async () => {
            await flushDrafts();
            await api.translation.start(project.id, run.id);
          },
          "",
          "resume",
        )
      }
    />
  );
  const exportControl = (
    <ActionControl
      label="Export translations…"
      variant={finished ? "primary" : "default"}
      disabled={action.busy || !loaded}
      pending={action.busy && action.key === "export"}
      pendingText="Exporting…"
      error={action.key === "export" ? action.error : ""}
      notice={action.key === "export" ? action.notice : ""}
      onClick={async () => {
        const done = await action.run(
          () => exportTranslation(project),
          "",
          "export",
        );
        if (done.ok && done.value) action.succeed(done.value, "export");
      }}
    />
  );
  // An example file for the user's own extractor to follow.
  const format = (
    <ActionRow
      title="File format"
      description="JSON or CSV, one line per message. The example shows every field your extractor can write."
    >
      <ActionControl
        label="Save example…"
        disabled={action.busy}
        pending={action.busy && action.key === "example"}
        pendingText="Saving…"
        error={action.key === "example" ? action.error : ""}
        notice={action.key === "example" ? action.notice : ""}
        onClick={async () => {
          const done = await action.run(
            async () => {
              const path = await window.dazedtl.saveTranslationFile(
                "Translation file example.json",
              );
              if (!path) return false;
              await api.translation.manualExample(project.id, path);
              return true;
            },
            "",
            "example",
          );
          if (done.ok && done.value)
            action.succeed("Example saved.", "example");
        }}
      />
    </ActionRow>
  );
  const skipped = load && load.unknown + load.changed + load.refused > 0;
  return (
    <PageLayout
      variant="editor"
      className="lens-method"
      aria-label="Manual workspace"
    >
      <PageHeader title="Manual" />
      <div className="frame-row">
        <Tabs
          id="manual"
          label="Manual sections"
          items={tabs}
          value={view}
          disabled={action.busy}
          onChange={(to) => void show(to)}
        />
      </div>
      <PageMessages>
        <Message
          message={
            [
              "load",
              "reload",
              "example",
              "estimate",
              "resume",
              "export",
              "approve",
              "pause",
            ].includes(action.key)
              ? ""
              : action.error
          }
          onDismiss={action.clear}
        />
        <GameWarnings warnings={state.warnings} />
      </PageMessages>
      <TabPanel id="manual" value={view}>
        {view === "text" && (
          <>
            <PageBody>
              <p className="muted lens-options-note">
                Your own tools extract the game&apos;s text into a translation
                file and write the translations back into the game. DazedTL
                translates the file&apos;s lines with your API key and the
                game&apos;s glossary.{" "}
                <HelpPopover label="Translation file" guide="manual">
                  A JSON or CSV file with one line per message: an ID your tools
                  can find it again by, the scene it belongs to, its source text
                  and its translation, empty until translated. Lines already
                  translated in the file are kept.
                </HelpPopover>
              </p>
              {loaded ? (
                <ActionList>
                  <ActionRow
                    title={<FileName name={loaded.name} />}
                    description={[
                      `${plural(loaded.lines, "line")} in ${plural(loaded.scenes, "scene")}`,
                      `loaded ${timeAgo(loaded.loaded, now)}`,
                      ...(loaded.translations
                        ? [
                            `${loaded.translations.toLocaleString()} translated in the file`,
                          ]
                        : []),
                    ].join(" · ")}
                  >
                    <ActionControl
                      label="Load again"
                      disabled={disabled}
                      disabledReason={
                        state.active
                          ? "Wait for the current work to finish."
                          : ""
                      }
                      title={loaded.path}
                      pending={action.busy && action.key === "reload"}
                      pendingText="Loading…"
                      error={action.key === "reload" ? action.error : ""}
                      notice={action.key === "reload" ? action.notice : ""}
                      onClick={() => void choose(loaded.path, "reload")}
                    />
                  </ActionRow>
                  {format}
                </ActionList>
              ) : (
                <>
                  <StatusPanel
                    title="Text file"
                    state="not_started"
                    guide="manual"
                    description="Load the file your extractor wrote. Nothing is sent until you approve an estimate."
                  />
                  <ActionList>{format}</ActionList>
                </>
              )}
              {skipped && <ImportSummary value={load} project={project} />}
            </PageBody>
            <ActionBar feedback={null}>
              <ActionControl
                label={loaded ? "Load another file…" : "Load text file…"}
                variant={loaded ? "default" : "primary"}
                disabled={disabled}
                disabledReason={
                  state.active ? "Wait for the current work to finish." : ""
                }
                pending={action.busy && action.key === "load"}
                pendingText="Loading…"
                error={action.key === "load" ? action.error : ""}
                notice={action.key === "load" ? action.notice : ""}
                onClick={() => void choose(null)}
              />
              {loaded && next("options")}
            </ActionBar>
          </>
        )}
        {view === "options" && (
          <>
            <PageBody ref={optionsBody}>
              <fieldset className="lens-options" disabled={disabled}>
                <GameLanguagesRow projectId={project.id} disabled={disabled} />
                <TranslationModeField
                  state={state}
                  options={options}
                  edit={edit}
                  disabled={disabled}
                  settings={settings}
                  agent={false}
                />
                <CheckGroup id="manual-scope" label="Translate" stacked>
                  <BaseGlossaryField options={options} edit={edit} />
                </CheckGroup>
                {/* With no assistant to install it, saving does (Translation.save). */}
                <CheckGroup
                  id="manual-tools"
                  label="Install in the game"
                  stacked
                >
                  <GameUpdateField
                    state={state}
                    options={options}
                    edit={edit}
                    settings={settings}
                    effect="Saving these options copies it into the game, or takes it out."
                  />
                </CheckGroup>
              </fieldset>
              <GameUpdateConfig
                project={project}
                state={state}
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
              {next("context")}
            </ActionBar>
          </>
        )}
        {view === "context" && (
          <ContextPanel
            state={state}
            copy={(variant) => next("progress", variant)}
          />
        )}
        {view === "progress" && (
          <>
            <PageBody>
              {!loaded && (
                <Notice>
                  <span>Load your text file first.</span>
                  <Button variant="link" onClick={() => void show("text")}>
                    Open Text
                  </Button>
                </Notice>
              )}
              <ApiRun
                run={run}
                redo={undefined}
                state={state}
                options={options}
                action={action}
                actions={resume}
                reestimate={false}
                waiting="Estimate the cost of the lines without a translation. Nothing is sent until you approve the estimate."
              />
            </PageBody>
            <ActionBar feedback={<Feedback dirty={draft.dirty} />}>
              {estimate}
              {exportControl}
            </ActionBar>
          </>
        )}
      </TabPanel>
    </PageLayout>
  );
}
