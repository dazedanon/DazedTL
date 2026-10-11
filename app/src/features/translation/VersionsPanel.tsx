import { useState } from "react";
import { api } from "../../api/client";
import type { Project, TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import { Button } from "../../ui/Button";
import { Section } from "../../ui/Section";
import { Message } from "../../ui/Feedback";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { ActionControl } from "../../ui/ActionControl";
import { JobStatus } from "../../ui/JobStatus";
import { StepProgress } from "../../ui/StepProgress";
import { ActionSlot } from "../../ui/ActionSlot";
import { VersionChanges } from "./VersionChanges";
import { VersionTools } from "./VersionTools";
import { ReleaseForm, emptyRelease } from "./ReleaseForm";
import {
  releaseEffect,
  removedFiles,
  stagedLayout,
  updateSteps,
  updateSummary,
  versionLabel,
  versionSession,
} from "./versionState";
import { displayText, sentence } from "../../ui/displayText";
import { useRead } from "../../state/useRead";

export function VersionsPanel({
  project,
  state,
  guided = false,
  onPrepare,
  onCheckpoint,
  actionTarget,
}: {
  project: Project;
  state: TranslationState;
  guided?: boolean;
  onPrepare?: () => void;
  onCheckpoint?: () => void;
  actionTarget?: HTMLElement | null;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [choosing, setChoosing] = useState(false);
  const [release, setRelease] = useState(emptyRelease);
  const [advanced, setAdvanced] = useState(false);
  const [dismissedAttempt, setDismissedAttempt] = useState<
    string | undefined
  >();
  const session = versionSession(
    state.jobs,
    state.git,
    state.lifecycle.discarded_release,
  );
  const disabled =
    action.busy || state.active || !!application.snapshot?.application.running;
  const pending = !!state.git?.pending_operations.length;
  const assetsPending = !!state.git?.asset_sync_pending;
  const active =
    session.latest &&
    ["ready", "running", "waiting"].includes(session.latest.status)
      ? session.latest
      : null;
  const stage =
    !choosing && session.stage?.status === "complete" ? session.stage : null;
  const preview = !choosing ? session.preview : undefined;
  const done = !choosing && session.finished;
  const aborted = !choosing && session.aborted;
  // Continue and cancel controls show their own outcome beside the action.
  const failedStep =
    session.latest &&
    ["failed", "interrupted"].includes(session.latest.status) &&
    !(
      pending &&
      ["version_continue", "version_abort"].includes(
        session.latest.action || "",
      )
    )
      ? session.latest
      : undefined;
  const layout = stagedLayout(session.stage);
  // A complete game missing most of the game's files is likely a patch.
  const removed = layout ? removedFiles(layout) : 0;
  const resultVersion =
    displayText(preview?.result?.version) ||
    displayText(stage?.result?.version);
  const operation = (name: string, args: Record<string, unknown> = {}) =>
    action.run(
      async () => {
        await flushDrafts();
        await api.translation.operation(project.id, name, args);
        if (name === "stage_update") setChoosing(false);
      },
      "",
      name,
    );
  const browse = (choose: (path: string) => void) =>
    action.run(
      async () => {
        const path = await window.dazedtl.chooseFolder();
        if (path) choose(path);
      },
      "",
      "folder",
    );
  const control = (
    name: string,
    label: string,
    args: Record<string, unknown> = {},
    blocked = false,
    primary = false,
  ) => (
    <ActionControl
      label={label}
      variant={primary ? "primary" : "default"}
      disabled={disabled || blocked}
      pending={action.busy && action.key === name}
      pendingText="Starting…"
      error={action.key === name ? action.error : ""}
      // Only this update's own step reports beside its control, never the
      // same step of an earlier update.
      job={
        !choosing || action.key === name
          ? session.current.find((job) => job.action === name)
          : undefined
      }
      onClick={() => operation(name, args)}
    />
  );
  const chooseNew = () => {
    // A finished update's release is not the next one.
    if (done) setRelease(emptyRelease);
    setChoosing(true);
    setDismissedAttempt(undefined);
    action.clear();
  };
  const configured = !!state.git?.configured;
  // The versions the game's history recorded, read again once it records another.
  const versions = useRead(
    configured ? `${project.id}\n${state.git?.original_commit}` : null,
    () => api.translation.versions(project.id),
  );
  const history = versions.value ?? [];
  const latest =
    history[0]?.version === state.git?.original_version
      ? history[0]
      : undefined;
  const earlier = latest ? history.slice(1) : history;
  // The update under way, from choosing its release to translating its text.
  const step = !configured
    ? null
    : choosing
      ? 0
      : pending || assetsPending
        ? 2
        : active
          ? ({ stage_update: 0, version_preview: 1, version_handoff: 3 }[
              active.action || ""
            ] ?? 2)
          : done
            ? 3
            : preview && !session.stale
              ? 2
              : stage || preview
                ? 1
                : session.stage &&
                    ["failed", "interrupted", "stopped"].includes(
                      session.stage.status,
                    ) &&
                    session.stage.id !== dismissedAttempt
                  ? 0
                  : null;
  // What holds the current step, said once beside it.
  const problem = pending
    ? "Conflicts to resolve"
    : assetsPending
      ? "Assets to recover"
      : failedStep
        ? sentence(failedStep.status)
        : "";
  return (
    <div className="version-panel">
      <div className="version-current">
        <span>Current game version</span>
        <strong>{state.git?.original_version || "Not recorded yet"}</strong>
        {latest && <small>{versionLabel(latest)}</small>}
      </div>
      {step !== null && (
        <StepProgress
          label="Game update steps"
          current={step}
          steps={updateSteps(session, layout, step, problem)}
        />
      )}
      {action.key === "folder" && (
        <Message message={action.error} onDismiss={action.clear} />
      )}
      {!configured ? (
        <Section title="Set up the game first">
          <p>Save the game’s version before bringing in an update.</p>
          <ActionSlot target={actionTarget}>
            {onPrepare ? (
              <Button variant="primary" onClick={onPrepare}>
                Go to setup
              </Button>
            ) : (
              <Button onClick={() => setAdvanced(true)}>
                Set up version tracking
              </Button>
            )}
          </ActionSlot>
        </Section>
      ) : pending || assetsPending ? (
        <Section title="Finish the interrupted update">
          {pending ? (
            <>
              <p>
                Remaining conflicts can be resolved using the official game’s
                files. Affected translated text may need translating again.
              </p>
              <ActionSlot target={actionTarget}>
                {control(
                  "version_continue",
                  "Use official files & continue",
                  {},
                  false,
                  true,
                )}
                {control(
                  "version_abort",
                  "Cancel update & restore translation",
                )}
              </ActionSlot>
            </>
          ) : (
            <p className="banner">
              The file update finished, but game assets still need recovery. Ask
              your coding assistant to finish asset synchronization in this game
              folder before starting another update.
            </p>
          )}
          {failedStep && <JobStatus job={failedStep} />}
        </Section>
      ) : active ? (
        <Section
          title={
            active.action === "stage_update"
              ? "Preparing the new release"
              : active.action === "version_preview"
                ? "Comparing game versions"
                : "Updating the game"
          }
        >
          <JobStatus job={active} />
          <ActionSlot target={actionTarget}>
            <ActionControl
              label="Stop at a safe point"
              disabled={action.busy || active.stop_requested}
              pending={action.busy && action.key === "stop-update"}
              pendingText="Requesting stop…"
              error={action.key === "stop-update" ? action.error : ""}
              onClick={() =>
                action.run(
                  () => api.translation.stop(project.id, active.id),
                  "Stop requested.",
                  "stop-update",
                )
              }
            />
          </ActionSlot>
        </Section>
      ) : done ? (
        <Section title="Game version updated">
          <p>
            Continue by having your coding assistant identify new or changed
            text and preserve translations that still apply.
          </p>
          <ActionSlot target={actionTarget}>
            {session.handoff ? (
              <ActionControl
                label="Copy post-update task"
                disabled={disabled}
                pending={action.busy && action.key === "copy-update"}
                pendingText="Copying…"
                error={action.key === "copy-update" ? action.error : ""}
                notice={action.key === "copy-update" ? action.notice : ""}
                onClick={() =>
                  action.run(
                    () =>
                      window.dazedtl.copyText(
                        String(session.handoff!.result!.prompt),
                      ),
                    "Task copied. Run it in your coding assistant.",
                    "copy-update",
                  )
                }
              />
            ) : (
              control(
                "version_handoff",
                "Prepare post-update task",
                {},
                false,
                true,
              )
            )}
            <Button variant="quiet" disabled={disabled} onClick={chooseNew}>
              Start another game update
            </Button>
          </ActionSlot>
        </Section>
      ) : preview && !session.stale ? (
        <Section
          title={`Review update to ${resultVersion}`}
          hint={[
            layout?.kind === "patch" && "Patch",
            updateSummary(preview.result!),
          ]
            .filter(Boolean)
            .join(" · ")}
          className="version-review"
        >
          {removed * 2 > (layout?.game_files ?? 0) && (
            <p className="banner">
              This release leaves out {removed.toLocaleString()} of the game’s{" "}
              {layout!.game_files.toLocaleString()} files, so applying it
              removes them. If it’s a patch, choose a different release and pick
              Patch.
            </p>
          )}
          <VersionChanges value={preview.result!} />
          <ActionSlot target={actionTarget}>
            {session.stage && (
              <Button
                variant="quiet"
                disabled={disabled}
                pending={action.busy && action.key === "discard_release"}
                onClick={() =>
                  operation("discard_release", { stage: session.stage!.id })
                }
              >
                Discard release
              </Button>
            )}
            <Button variant="quiet" disabled={disabled} onClick={chooseNew}>
              Choose a different release
            </Button>
            {control(
              "version_apply",
              `Apply update to ${resultVersion}`,
              { preview_id: preview.id },
              false,
              true,
            )}
          </ActionSlot>
        </Section>
      ) : stage || (preview && session.stale) ? (
        <Section title={`Compare with version ${resultVersion}`}>
          <p>
            {layout?.kind === "patch"
              ? `The patch was copied for comparison. ${releaseEffect(layout)}`
              : "The new release was copied for comparison."}{" "}
            Preview its changes before updating the game.
          </p>
          {stage?.result?.preparation_required === true && (
            <>
              <p className="banner">
                This engine needs assistant preparation. Prepare the copied game
                through the same engine-specific process used for the current
                original, then preview the changes.
              </p>
              <p className="translation-path muted">
                Copied release: {String(stage.result.official)}
              </p>
            </>
          )}
          {session.stale && (
            <p className="banner">
              The current game changed after the last comparison. Preview it
              again before applying the update.
            </p>
          )}
          <ActionSlot target={actionTarget}>
            {session.stage && (
              <Button
                variant="quiet"
                disabled={disabled}
                pending={action.busy && action.key === "discard_release"}
                onClick={() =>
                  operation("discard_release", { stage: session.stage!.id })
                }
              >
                Discard release
              </Button>
            )}
            <Button variant="quiet" disabled={disabled} onClick={chooseNew}>
              Choose a different release
            </Button>
            {control(
              "version_preview",
              "Preview changes",
              {
                official:
                  stage?.result?.official || preview?.result?.source_root,
                version: resultVersion,
              },
              !state.git?.worktree_clean,
              true,
            )}
          </ActionSlot>
        </Section>
      ) : choosing ||
        (session.stage &&
          ["failed", "interrupted", "stopped"].includes(session.stage.status) &&
          session.stage.id !== dismissedAttempt) ? (
        <ReleaseForm
          projectId={project.id}
          value={release}
          onChange={setRelease}
          disabled={disabled}
          browse={browse}
          actionTarget={actionTarget}
          footer={(request) => (
            <>
              <Button
                variant="quiet"
                disabled={disabled}
                onClick={() => {
                  setChoosing(false);
                  setDismissedAttempt(session.stage?.id);
                }}
              >
                Cancel
              </Button>
              {control(
                "stage_update",
                "Prepare new release",
                request ?? {},
                !request,
                true,
              )}
            </>
          )}
        />
      ) : (
        <Section title="Update the game">
          <p>
            {aborted
              ? "The update was canceled. Choose another release when you’re ready."
              : "When the developer releases a new version or a patch, bring it in here. Your translation carries over, so only new and changed text needs translating."}
          </p>
          <ActionSlot target={actionTarget}>
            <Button variant="primary" disabled={disabled} onClick={chooseNew}>
              Start game update
            </Button>
          </ActionSlot>
        </Section>
      )}
      {configured &&
        !state.git?.worktree_clean &&
        !pending &&
        !assetsPending && (
          <ActionList>
            <ActionRow
              label={
                <>
                  <strong>Save current translation changes first</strong>
                  <small>
                    The version comparison requires your reviewed game edits to
                    be saved in Git.
                  </small>
                </>
              }
            >
              <Button
                disabled={disabled}
                onClick={() =>
                  onCheckpoint ? onCheckpoint() : setAdvanced(true)
                }
              >
                Review translation checkpoint
              </Button>
            </ActionRow>
          </ActionList>
        )}
      {!guided && (
        <details
          open={advanced}
          onToggle={(event) => setAdvanced(event.currentTarget.open)}
        >
          <summary>Advanced setup & patch tools</summary>
          <VersionTools
            state={state}
            disabled={disabled}
            browse={browse}
            control={control}
          />
        </details>
      )}
      {(step === null || done) && !!earlier.length && (
        <Section title="Earlier versions" className="version-history">
          <ol>
            {earlier.map((record) => (
              <li key={record.commit}>
                <strong>{record.version}</strong>
                <span>{versionLabel(record)}</span>
              </li>
            ))}
          </ol>
        </Section>
      )}
      {!guided && !!session.history.length && (
        <details>
          <summary>Update history ({session.history.length})</summary>
          {session.history.map((job) => (
            <article className="translation-run" key={job.id}>
              <JobStatus job={job} />
              <time className="muted" dateTime={job.created}>
                {new Date(job.created).toLocaleString()}
              </time>
            </article>
          ))}
        </details>
      )}
    </div>
  );
}
