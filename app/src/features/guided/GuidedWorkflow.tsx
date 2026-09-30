import { useState } from "react";
import { ArrowRight, ArrowLeft, Play, RefreshCw } from "lucide-react";
import { api } from "../../api/client";
import { flushDrafts } from "../../state/leaveGuards";
import type { Phase, Preview, Project, RunMode } from "../../api/contracts";
import { Modal } from "../../ui/Modal";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import ContextEditor from "./ContextEditor";
import RunPanel from "./RunPanel";
import { useGuidedWorkflow } from "./useGuidedWorkflow";

export default function GuidedWorkflow({
  project,
  settings,
}: {
  project: Project;
  settings: () => void;
}) {
  const {
    state,
    action: feedback,
    stage,
    selected,
    setSelected,
    mode,
    setMode,
    move,
    running,
  } = useGuidedWorkflow(project);
  const { busy, error } = feedback;
  const action = feedback.run;
  const report = feedback.report;
  const disabled = busy || running;
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirm, setConfirm] = useState("");
  const [output, setOutput] = useState("");
  const latest = state?.operations[0];
  const job = state?.run;
  if (!state)
    return project.available === false ? (
      <Message message="The game folder is unavailable. Reconnect its drive or open the game from Overview." />
    ) : (
      <p className="muted">Opening Guided Workflow…</p>
    );
  return (
    <section className="guided-workspace">
      <header className="page-heading">
        <div>
          <h1>Guided Workflow</h1>
          <p>{project.name} · RPG Maker MV / MZ</p>
        </div>
      </header>
      <nav className="steps" aria-label="Guided steps">
        {[
          ["files", "1", "Files"],
          ["context", "2", "Context"],
          ["translate", "3", "Translate"],
        ].map(([id, number, label]) => (
          <Button
            size="comfortable"
            key={id}
            aria-current={stage === id ? "step" : undefined}
            disabled={
              busy || (id === "translate" && !state.importedFiles.length)
            }
            onClick={() => move(id)}
          >
            <span>{number}</span>
            {label}
          </Button>
        ))}
      </nav>
      <Message message={error} onDismiss={feedback.clear} />
      {stage === "files" && (
        <section className="card">
          <div className="section-heading">
            <h2>Choose the files to work on</h2>
            <span className="muted">{selected.length} selected</span>
          </div>
          <p className="muted">
            Selected game data is copied into this project’s workspace.
          </p>
          <div className="actions">
            <Button
              size="comfortable"
              disabled={disabled}
              onClick={() => setSelected(state.files.map((f) => f.name))}
            >
              Select all
            </Button>
            <Button
              size="comfortable"
              disabled={disabled}
              onClick={() => setSelected([])}
            >
              Clear selection
            </Button>
          </div>
          <div className="file-list">
            {state.files.map((file) => (
              <label key={file.name}>
                <input
                  type="checkbox"
                  checked={selected.includes(file.name)}
                  disabled={disabled}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? [...selected, file.name]
                        : selected.filter((name) => name !== file.name),
                    )
                  }
                />
                {file.name}
              </label>
            ))}
          </div>
          <div className="actions">
            <Button
              size="comfortable"
              variant="primary"
              disabled={disabled || !selected.length}
              onClick={() =>
                action(async () =>
                  setPreview(await api.preview(project.id, "import", selected)),
                )
              }
            >
              Import selected files
            </Button>
            {!!state.importedFiles.length && (
              <Button
                size="comfortable"
                disabled={busy}
                onClick={() => move("context")}
              >
                Review context
                <ArrowRight size={16} />
              </Button>
            )}
          </div>
        </section>
      )}
      <div hidden={stage !== "context"}>
        <ContextEditor
          projectId={project.id}
          documents={state.documents}
          recovered={state.drafts || {}}
          disabled={disabled}
        />
        <div className="actions">
          <Button size="comfortable" onClick={() => move("files")}>
            <ArrowLeft size={16} />
            Files
          </Button>
          <Button
            size="comfortable"
            variant="primary"
            disabled={disabled || !state.importedFiles.length}
            onClick={() => move("translate")}
          >
            Continue to translation
            <ArrowRight size={16} />
          </Button>
        </div>
      </div>
      {stage === "translate" && (
        <section className="card">
          <h2>Translate this phase</h2>
          <div className="form-grid">
            <label>
              Phase
              <select
                disabled={disabled}
                value={state.phase}
                onChange={(e) =>
                  action(async () => {
                    await api.phase(project.id, e.target.value as Phase);
                  })
                }
              >
                <option value="database">Database text and names</option>
                <option value="dialogue">Dialogue and choices</option>
              </select>
            </label>
            <label>
              Run mode
              <select
                disabled={disabled}
                value={mode}
                onChange={(e) => setMode(e.target.value as RunMode)}
              >
                <option value="translate" disabled={!state.provider.enabled}>
                  Live translation
                </option>
                <option
                  value="batch"
                  disabled={
                    !state.provider.enabled || !state.provider.batchSupported
                  }
                >
                  Batch translation
                </option>
                <option value="estimate">Estimate cost</option>
              </select>
            </label>
          </div>
          <p className="muted">
            {state.provider.model} · {state.phaseFiles.length} imported files in
            this phase
          </p>
          <details>
            <summary>Files in this phase</summary>
            <ul>
              {state.phaseFiles.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          </details>
          <p className="footnote">
            The existing RPG Maker engine handles parsing, speaker context, the
            glossary, and phase-specific translation rules.
          </p>
          {!state.provider.ready && mode !== "estimate" ? (
            <Button size="comfortable" variant="primary" onClick={settings}>
              Set up a provider
            </Button>
          ) : (
            <Button
              size="comfortable"
              variant="primary"
              disabled={disabled || !state.phaseFiles.length}
              onClick={() =>
                mode === "estimate"
                  ? action(async () => {
                      await flushDrafts();
                      await api.start(project.id, mode);
                    })
                  : setConfirm("start")
              }
            >
              <Play size={16} />
              {mode === "estimate"
                ? "Estimate this phase"
                : mode === "batch"
                  ? "Prepare batch translation"
                  : "Start live translation"}
            </Button>
          )}
        </section>
      )}
      {latest && (
        <section className="operation">
          <strong>
            {latest.label} · {latest.status}
          </strong>
          <p>{latest.message}</p>
          {latest.status === "running" && (
            <Button
              size="comfortable"
              onClick={() =>
                action(async () => {
                  await api.stop(project.id);
                })
              }
            >
              Stop preparation
            </Button>
          )}
        </section>
      )}
      {job && (
        <RunPanel
          job={job}
          active={running && job.status !== "complete"}
          busy={busy}
          stop={() =>
            action(async () => {
              await api.stop(project.id);
            })
          }
          resume={() => setConfirm("resume")}
          answer={(approved) =>
            action(async () => {
              await api.answer(project.id, job.approval!.token, approved);
            })
          }
          exportFiles={() =>
            action(async () => {
              const result = await api.export(project.id);
              setOutput(result.path);
            })
          }
          apply={() =>
            action(async () =>
              setPreview(await api.preview(project.id, "export_selected")),
            )
          }
        />
      )}
      {state.collectionError && (
        <p className="banner">{state.collectionError}</p>
      )}
      {output && (
        <div className="output">
          <span>{output}</span>
          <Button
            size="comfortable"
            onClick={() =>
              window.dazedtl.openFolder("output", output).catch(report)
            }
          >
            Open output folder
          </Button>
        </div>
      )}
      <Button
        size="comfortable"
        variant="quiet"
        className="refresh"
        disabled={busy}
        onClick={() => action(async () => {})}
      >
        <RefreshCw size={15} />
        Refresh status
      </Button>
      {preview && (
        <Modal
          label="Review guided action"
          onDismiss={() => setPreview(null)}
          dismissible={!busy}
        >
          <h2>{preview.label}</h2>
          <p>{preview.files} selected files</p>
          <p className="path">{preview.destination}</p>
          <ul>
            {preview.options.files.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
          <p>
            {preview.label.includes("Import")
              ? "The source game files stay unchanged."
              : "This replaces the selected game data with the completed translation."}
          </p>
          {error && <p className="banner">{error}</p>}
          <div className="actions">
            <Button
              size="comfortable"
              disabled={busy}
              onClick={() => setPreview(null)}
            >
              Cancel
            </Button>
            <Button
              size="comfortable"
              variant="primary"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await api.execute(project.id, preview.token);
                  setPreview(null);
                })
              }
            >
              {preview.label.includes("Import")
                ? "Copy selected files"
                : "Apply to game"}
            </Button>
          </div>
        </Modal>
      )}
      {confirm && (
        <Modal
          label="Start translation"
          onDismiss={() => setConfirm("")}
          dismissible={!busy}
        >
          <h2>
            {confirm === "resume"
              ? "Resume this run?"
              : mode === "batch"
                ? "Prepare this batch?"
                : "Start live translation?"}
          </h2>
          <p>
            {confirm === "resume"
              ? "Continue using the run’s frozen inputs, context, and provider settings."
              : `${state.phaseFiles.length} files will use ${state.provider.model} and the saved game context.`}
          </p>
          <p>
            {mode === "batch" && confirm !== "resume"
              ? "You will review the collected batch before submission. Speaker preparation may request separate approval."
              : "Provider requests may incur charges."}
          </p>
          {error && <p className="banner">{error}</p>}
          <div className="actions">
            <Button
              size="comfortable"
              disabled={busy}
              onClick={() => setConfirm("")}
            >
              Cancel
            </Button>
            <Button
              size="comfortable"
              variant="primary"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await flushDrafts();
                  if (confirm === "resume") await api.resume(project.id);
                  else await api.start(project.id, mode);
                  setConfirm("");
                })
              }
            >
              Continue
            </Button>
          </div>
        </Modal>
      )}
    </section>
  );
}
