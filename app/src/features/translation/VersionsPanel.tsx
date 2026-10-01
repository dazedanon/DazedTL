import { useState } from "react";
import { api } from "../../api/client";
import type { Project, TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import { Button } from "../../ui/Button";
import { Section } from "../../ui/Section";
import { Message } from "../../ui/Feedback";
import { BackupsPanel, BackupSummary } from "./BackupsPanel";

export function VersionsPanel({
  project,
  state,
}: {
  project: Project;
  state: TranslationState;
}) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const [version, setVersion] = useState(state.git?.original_version || "");
  const [manifest, setManifest] = useState(
    ".dazedtl/len-method/work/patch-files.json",
  );
  const [untranslated, setUntranslated] = useState(false);
  const [original, setOriginal] = useState("");
  const [official, setOfficial] = useState("");
  const [nextVersion, setNextVersion] = useState("");
  const operation = (name: string, args: Record<string, unknown> = {}) =>
    action.run(async () => {
      await flushDrafts();
      await api.translation.operation(project.id, name, args);
    });
  const disabled = action.busy || state.active;
  const previews = state.jobs.filter(
    (job) =>
      job.kind === "operation" &&
      job.status === "complete" &&
      job.result?.proposed_tree,
  );
  return (
    <>
      <Message message={action.error} onDismiss={action.clear} />
      <Section title="Source and version tracking">
        <dl className="translation-facts">
          <div>
            <dt>Source game version</dt>
            <dd>{state.git?.original_version || "Not recorded"}</dd>
          </div>
          <div>
            <dt>Translation branch</dt>
            <dd>{state.git?.translation_branch || "Not established"}</dd>
          </div>
          <div>
            <dt>Translation commit</dt>
            <dd>
              {state.git?.translation_commit?.slice(0, 12) || "No checkpoint"}
            </dd>
          </div>
          <div>
            <dt>Source backup</dt>
            <dd>
              <BackupSummary record={state.lifecycle.source_backup} fallback="Required before preparation" />
            </dd>
          </div>
          <div>
            <dt>Workspace backup</dt>
            <dd>
              <BackupSummary record={state.lifecycle.workspace_backup} fallback="Not yet saved" />
            </dd>
          </div>
        </dl>
        <p className="muted">
          The original branch holds untranslated patch files. Translation work
          goes on the registered translation branch. Glossary, working stores,
          and QA records have separate backups.
        </p>
        <div className="actions">
          <Button
            disabled={disabled}
            onClick={() => operation("backup_source")}
          >
            Back up source game
          </Button>
          <Button
            disabled={disabled || !state.initialized}
            onClick={() => operation("backup_workspace")}
          >
            Back up translation workspace
          </Button>
          {["MVMZ", "ACE"].includes(project.engine) && (
            <Button
              disabled={disabled || !state.lifecycle.source_backup}
              onClick={() => operation("rpgmaker_prepare")}
            >
              Prepare RPG Maker files
            </Button>
          )}
        </div>
        <details>
          <summary>Establish or reuse Git baselines</summary>
          <div className="form-grid">
            <label>
              Source game version
              <input
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                placeholder="For example, 1.00"
              />
            </label>
            <label>
              Runtime patch manifest, relative to the game
              <input
                value={manifest}
                onChange={(event) => setManifest(event.target.value)}
              />
            </label>
          </div>
          <label className="translation-check">
            <input
              type="checkbox"
              checked={untranslated}
              onChange={(event) => setUntranslated(event.target.checked)}
            />
            The selected folder has been checked and is untranslated.
          </label>
          <label>
            Separate matching original, if needed
            <div className="actions">
              <input
                value={original}
                onChange={(event) => setOriginal(event.target.value)}
              />
              <Button
                onClick={() =>
                  action.run(async () => {
                    const path = await window.dazedtl.chooseFolder();
                    if (path) setOriginal(path);
                  })
                }
              >
                Browse
              </Button>
            </div>
          </label>
          <Button
            disabled={
              disabled || !version.trim() || !state.lifecycle.source_backup
            }
            onClick={() =>
              operation("git_setup", {
                version,
                manifest,
                untranslated,
                original,
              })
            }
          >
            Establish baselines
          </Button>
        </details>
      </Section>
      <BackupsPanel state={state} />
      <Section title="Checkpoint and local delivery">
        <label>
          Complete runtime patch manifest
          <input
            value={manifest}
            onChange={(event) => setManifest(event.target.value)}
          />
        </label>
        <div className="actions">
          <Button
            disabled={disabled || !state.git?.configured}
            onClick={() => operation("checkpoint", { manifest })}
          >
            Checkpoint reviewed patch
          </Button>
          <Button
            disabled={
              disabled ||
              !state.lifecycle.checkpoint ||
              state.progress?.phases.qa !== "complete"
            }
            onClick={() => operation("package")}
          >
            Build local patch
          </Button>
        </div>
        {state.lifecycle.delivery && (
          <p className="translation-path">
            {state.lifecycle.delivery.path}
            <br />
            Commit {state.lifecycle.delivery.commit.slice(0, 12)} · game{" "}
            {state.lifecycle.delivery.game_version}
          </p>
        )}
      </Section>
      <Section title="Update to a new game release">
        <p className="muted">
          Preview the official changes against the recorded original and
          translation. Resolve conflicts before resuming translation.
        </p>
        <label>
          New official game folder
          <div className="actions">
            <input
              value={official}
              onChange={(event) => setOfficial(event.target.value)}
            />
            <Button
              onClick={() =>
                action.run(async () => {
                  const path = await window.dazedtl.chooseFolder();
                  if (path) setOfficial(path);
                })
              }
            >
              Browse
            </Button>
          </div>
        </label>
        <label>
          New game version
          <input
            value={nextVersion}
            onChange={(event) => setNextVersion(event.target.value)}
          />
        </label>
        <Button
          disabled={
            disabled || !official || !nextVersion || !state.git?.configured
          }
          onClick={() =>
            operation("stage_update", { official, version: nextVersion })
          }
        >
          Stage and prepare new original
        </Button>
        <p className="footnote">
          Preview a copy prepared through the same engine-specific route as the
          current baseline. The selected official folder stays unchanged.
        </p>
        <Button
          disabled={
            disabled || !official || !nextVersion || !state.git?.configured
          }
          onClick={() =>
            operation("version_preview", { official, version: nextVersion })
          }
        >
          Preview official update
        </Button>
        {previews.map((job) => (
          <details key={job.id}>
            <summary>
              Preview · {new Date(job.created).toLocaleString()}
            </summary>
            <pre className="translation-json">
              {JSON.stringify(job.result, null, 2)}
            </pre>
            <Button
              disabled={disabled}
              onClick={() => operation("version_apply", { preview_id: job.id })}
            >
              Apply this reviewed update
            </Button>
          </details>
        ))}
        {!!state.git?.pending_operations.length && (
          <div className="actions">
            <Button
              disabled={disabled}
              onClick={() => operation("version_continue")}
            >
              Continue resolved update
            </Button>
            <Button
              disabled={disabled}
              onClick={() => operation("version_abort")}
            >
              Abort update
            </Button>
          </div>
        )}
        <Button
          disabled={disabled || !state.git?.configured}
          onClick={() => operation("version_handoff")}
        >
          Prepare post-update instructions
        </Button>
      </Section>
      <Section title="Saved operations">
        {!state.jobs.some((job) => job.kind === "operation") && (
          <p className="muted">
            The starting prompt will perform these steps and report its saved
            checkpoints.
          </p>
        )}
        {state.jobs
          .filter((job) => job.kind === "operation")
          .map((job) => (
            <article className="translation-run" key={job.id}>
              <strong>
                {job.label} · {job.status.replaceAll("_", " ")}
              </strong>
              <p>{job.message}</p>
              {job.status === "running" && (
                <Button
                  disabled={action.busy || job.stop_requested}
                  onClick={() =>
                    action.run(() => api.translation.stop(project.id, job.id))
                  }
                >
                  Stop at checkpoint
                </Button>
              )}
              {typeof job.result?.prompt === "string" && (
                <Button
                  onClick={() =>
                    action.run(() =>
                      window.dazedtl.copyText(String(job.result!.prompt)),
                    )
                  }
                >
                  Copy update instructions
                </Button>
              )}
              {typeof job.result?.official === "string" && (
                <Button
                  onClick={() => {
                    setOfficial(String(job.result!.official));
                    setNextVersion(String(job.result!.version));
                  }}
                >
                  Use staged original for preview
                </Button>
              )}
              {job.result && (
                <details>
                  <summary>Saved evidence and paths</summary>
                  <pre className="translation-json">
                    {JSON.stringify(job.result, null, 2)}
                  </pre>
                </details>
              )}
            </article>
          ))}
      </Section>
    </>
  );
}
