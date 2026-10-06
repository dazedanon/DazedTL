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
import { ActionList, ActionRow } from "../../ui/ActionList";
import { engineLabel } from "../../ui/displayText";
import { Section } from "../../ui/Section";
import { Tabs, TabPanel, type Tab } from "../../ui/Tabs";
import { Button } from "../../ui/Button";
import { Feedback, Message } from "../../ui/Feedback";
import { useProjectOptions } from "./useProjectOptions";
import { ContextPanel } from "./ContextPanel";
import { RequestsPanel } from "./RequestsPanel";
import { VersionsPanel } from "./VersionsPanel";
import { JobStatus } from "../../ui/JobStatus";
import { ImageManager } from "../images/ImageManager";
import { ImageTextEditor } from "../images/ImageTextEditor";

type View = "progress" | "context" | "requests" | "versions";
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
  openGuided,
}: {
  project: Project;
  settings: () => void;
  /** Opens the Translation screen when this game also has phased work there. */
  openGuided?: () => void;
}) {
  const application = useApplication();
  const state = application.snapshot?.translation;
  if (!state || state.projectId !== project.id)
    return (
      <PageLayout>
        <PageHeader title="Len's method" />
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
      openGuided={openGuided}
    />
  );
}

function Workspace({
  project,
  state,
  settings,
  openGuided,
}: {
  project: Project;
  state: TranslationState;
  settings: () => void;
  openGuided?: () => void;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const draft = useProjectOptions(state, action.report);
  const [view, setView] = useState<View>("progress");
  const [imageManager, setImageManager] = useState(false);
  const [editorAssets, setEditorAssets] = useState<string[] | null>(null);
  const [versionActions, setVersionActions] = useState<HTMLDivElement | null>(
    null,
  );
  const tabs: Tab<View>[] = [
    { id: "progress", label: "Progress" },
    { id: "context", label: "Context" },
    { id: "requests", label: "Requests & results" },
    { id: "versions", label: "Game updates" },
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
  if (imageManager)
    return (
      <>
        <ImageManager
          projectId={project.id}
          observed={application.snapshot?.images}
          backLabel="Back to Len’s method"
          onClose={() => setImageManager(false)}
          onOpenEditor={setEditorAssets}
        />
        {editorAssets && (
          <ImageTextEditor
            projectId={project.id}
            assetIds={editorAssets}
            observationKey={application.snapshot}
            onClose={() => setEditorAssets(null)}
          />
        )}
      </>
    );
  return (
    <PageLayout
      variant="editor"
      className="lens-method"
      aria-label="Len's method workspace"
    >
      <PageHeader
        title="Len's method"
        description={project.name + " · " + engineLabel(state.engine)}
        actions={
          <div className="actions">
            <Button
              disabled={action.busy || !state.initialized}
              onClick={() =>
                action.run(() => window.dazedtl.openFolder("projectWorkspace"))
              }
            >
              <FolderOpen size={16} />
              Workspace
            </Button>
            <Button
              disabled={disabled}
              onClick={() =>
                action.run(async () => {
                  await flushDrafts();
                  setImageManager(true);
                })
              }
            >
              Image Manager
            </Button>
          </div>
        }
      />
      <div className="frame-row">
        <Tabs
          id="translation"
          label="Len's method sections"
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
              <Section title="Translation approach">
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
                  <p className="muted">
                    The starting prompt handles engine investigation, setup,
                    translation, and delivery. The app tracks saved work across
                    every mode.
                  </p>
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
                          <dd>{state.connection?.model || "Not selected"}</dd>
                        </div>
                      </dl>
                      <Button onClick={settings}>
                        Choose connection and model
                      </Button>
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
              <Section
                title="Saved progress"
                hint={
                  progress?.updated_at
                    ? "Last report: " +
                      new Date(progress.updated_at).toLocaleString()
                    : "Awaiting the first saved report"
                }
              >
                <div className="translation-phases">
                  {Object.entries(labels).map(([key, label]) => (
                    <div
                      key={key}
                      data-state={progress?.phases[key] || "pending"}
                    >
                      <span>{label}</span>
                      <strong>
                        {(progress?.phases[key] || "pending").replaceAll(
                          "_",
                          " ",
                        )}
                      </strong>
                    </div>
                  ))}
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
                {progress?.blocker && (
                  <p className="banner">{progress.blocker}</p>
                )}
                <p>
                  {progress?.next_action ||
                    "Copy the starting prompt. Setup establishes source backups, version baselines, and shared guidance before translation."}
                </p>
                <p className="footnote">
                  These are saved checkpoints. An external assistant's last
                  report does not establish that its session is still running.
                  Text completion does not establish runtime QA completion.
                </p>
              </Section>
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
                      Pause at checkpoint
                    </Button>
                  )}
                </Section>
              )}
              <Section title="Preparation checkpoints">
                <dl className="translation-facts">
                  <div>
                    <dt>Source backup</dt>
                    <dd>
                      {state.lifecycle.source_backup?.available === false
                        ? "Unavailable"
                        : state.lifecycle.source_backup
                          ? "Saved"
                          : "Pending"}
                    </dd>
                  </div>
                  <div>
                    <dt>Original / translation branches</dt>
                    <dd>{state.git?.configured ? "Established" : "Pending"}</dd>
                  </div>
                  <div>
                    <dt>Source game version</dt>
                    <dd>{state.git?.original_version || "Not recorded"}</dd>
                  </div>
                  <div>
                    <dt>Translation checkpoint</dt>
                    <dd>{state.git?.translation_commit ? "Saved" : "None"}</dd>
                  </div>
                </dl>
              </Section>
              {openGuided && (
                <ActionList>
                  <ActionRow
                    title="Existing phased work"
                    description="Runs and choices from the Translation screen stay there."
                  >
                    <Button onClick={openGuided}>Open Translation</Button>
                  </ActionRow>
                </ActionList>
              )}
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
        {view === "requests" && (
          <>
            <PageBody>
              <RequestsPanel state={state} />
            </PageBody>
            <ActionBar feedback={null}>{copyControl()}</ActionBar>
          </>
        )}
        {view === "versions" && (
          <>
            <PageBody>
              <VersionsPanel
                project={project}
                state={state}
                actionTarget={versionActions}
              />
            </PageBody>
            {/* Update steps lead here; the prompt copy steps back. */}
            <ActionBar feedback={null}>
              <div ref={setVersionActions} className="action-bar-slot" />
              {copyControl("default")}
            </ActionBar>
          </>
        )}
      </TabPanel>
    </PageLayout>
  );
}
