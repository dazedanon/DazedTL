import { useState, type ReactNode } from "react";
import { Clipboard, FolderOpen } from "lucide-react";
import { api } from "../../api/client";
import type {
  Project,
  TranslationOptions,
  TranslationState,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import { PageLayout, PageHeader } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { Tabs, TabPanel, type Tab } from "../../ui/Tabs";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { useProjectOptions } from "./useProjectOptions";
import { ContextPanel } from "./ContextPanel";
import { RequestsPanel } from "./RequestsPanel";
import { VersionsPanel } from "./VersionsPanel";
import { JobStatus } from "../../ui/JobStatus";
import "./translation.css";
import { ImageManager } from "../images/ImageManager";
import { ImageTextEditor } from "../images/ImageTextEditor";

type View = "progress" | "context" | "requests" | "versions" | "legacy";
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
  legacy,
}: {
  project: Project;
  settings: () => void;
  legacy: ReactNode;
}) {
  const application = useApplication();
  const state = application.snapshot?.translation;
  if (!state || state.projectId !== project.id)
    return (
      <PageLayout>
        <PageHeader title="Translation" />
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
      legacy={legacy}
    />
  );
}

function Workspace({
  project,
  state,
  settings,
  legacy,
}: {
  project: Project;
  state: TranslationState;
  settings: () => void;
  legacy: ReactNode;
}) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const draft = useProjectOptions(state, action.report);
  const [view, setView] = useState<View>("progress");
  const [imageManager, setImageManager] = useState(false);
  const [editorAssets, setEditorAssets] = useState<string[] | null>(null);
  const tabs: Tab<View>[] = [
    { id: "progress", label: "Progress" },
    { id: "context", label: "Context" },
    { id: "requests", label: "Requests & results" },
    { id: "versions", label: "Game updates" },
    ...(legacy
      ? [{ id: "legacy" as const, label: "Existing phased work" }]
      : []),
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
    action.run(async () => {
      await flushDrafts();
      if (draft.dirty) await draft.save();
      const result = await api.translation.prepare(project.id);
      await window.dazedtl.copyText(result.handoff);
    }, "Starting prompt copied. Paste it into your coding assistant to begin or resume.");
  const progress = state.progress;
  const text = progress?.metrics.text;
  const latest = state.jobs[0];
  if (imageManager) {
    if (editorAssets) return <ImageTextEditor projectId={project.id} assetIds={editorAssets} observationKey={application.snapshot} onClose={() => setEditorAssets(null)} />;
    return <ImageManager projectId={project.id} observed={application.snapshot?.images} backLabel="Back to Len’s method"
      onClose={() => setImageManager(false)} onOpenEditor={setEditorAssets} />;
  }
  return (
    <PageLayout
      className="translation-workspace"
      aria-label="Translation workspace"
    >
      <PageHeader
        title="Translation"
        description={project.name + " · " + state.engine}
        divided
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
            <Button disabled={disabled} onClick={() => action.run(async () => { await flushDrafts(); setImageManager(true); })}>Image Manager</Button>
            <Button variant="primary" disabled={disabled} onClick={copy}>
              <Clipboard size={16} />
              {draft.dirty
                ? "Save and copy starting prompt"
                : "Copy starting prompt"}
            </Button>
          </div>
        }
      />
      <Message message={action.error} onDismiss={action.clear} />
      {action.notice && (
        <p role="status" className="translation-notice">
          {action.notice}
        </p>
      )}
      {state.warnings.map((warning) => (
        <p className="banner" key={warning}>
          {warning}
        </p>
      ))}
      {progress?.warnings?.map((warning) => (
        <p className="banner" key={warning}>
          {warning}
        </p>
      ))}
      <Tabs
        id="translation"
        label="Translation project"
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
      <TabPanel id="translation" value={view}>
        {view === "progress" && (
          <>
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
                    <dl className="translation-facts" aria-label="Current API selection">
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
                {draft.dirty && (
                  <div className="actions">
                    <Button onClick={() => action.run(draft.save)}>
                      Save project options
                    </Button>
                    <Button onClick={() => action.run(draft.discard)}>
                      Discard draft
                    </Button>
                    <small>Draft saved for recovery.</small>
                  </div>
                )}
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
              {text && (
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
                  <p>
                    <strong>{text.reviewed.toLocaleString()}</strong>{" "}
                    source-checked
                  </p>
                  <p>
                    {text.total === null
                      ? "Full coverage has not yet been audited."
                      : "Source inventory reported complete."}
                  </p>
                </div>
              )}
              {state.options.include_images && progress && (
                <p>
                  Images: {progress.metrics.images.translated} translated /{" "}
                  {progress.metrics.images.total ?? "unknown total"}
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
                These are saved checkpoints. An external assistant's last report
                does not establish that its session is still running. Text
                completion does not establish runtime QA completion.
              </p>
            </Section>
            {latest && (
              <Section title="Latest app operation">
                <JobStatus job={latest} />
                {latest.kind === "translation" && (
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
                  <dd>{state.lifecycle.source_backup?.available === false ? "Unavailable" : state.lifecycle.source_backup ? "Saved" : "Pending"}</dd>
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
                  <dd>
                    {state.git?.translation_commit?.slice(0, 12) || "None"}
                  </dd>
                </div>
              </dl>
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
          </>
        )}
        {view === "context" && <ContextPanel state={state} />}
        {view === "requests" && <RequestsPanel state={state} />}
        {view === "versions" && (
          <VersionsPanel project={project} state={state} />
        )}
        {view === "legacy" && legacy}
      </TabPanel>
    </PageLayout>
  );
}
