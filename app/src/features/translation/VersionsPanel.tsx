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
import { fileLines } from "../guided/translationView";
import { VersionChanges } from "./VersionChanges";
import { VersionTools } from "./VersionTools";
import { ReleaseForm, emptyRelease } from "./ReleaseForm";
import {
  guidedUpdateTasks,
  interruptedUpdate,
  releaseEffect,
  removedFiles,
  stagedLayout,
  textChanges,
  textSummary,
  updateSteps,
  updateSummary,
  versionSession,
} from "./versionState";
import { displayText, selectionNames, sentence } from "../../ui/displayText";

export function VersionsPanel({
  project,
  state,
  guided = false,
  onPrepare,
  openTask,
  openFiles,
  actionTarget,
}: {
  project: Project;
  state: TranslationState;
  guided?: boolean;
  onPrepare?: () => void;
  /** Opens a Guided task, where a finished update's new text is translated. */
  openTask?: (step: string, task: string) => void;
  /** Opens a Guided translate task with the given files selected. */
  openFiles?: (group: "database" | "dialogue", files: string[]) => void;
  actionTarget?: HTMLElement | null;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
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
  const active =
    session.latest &&
    ["ready", "running", "waiting"].includes(session.latest.status)
      ? session.latest
      : null;
  // A stopped update whose assets wait either reached the translation, and
  // finishing copies them, or never did, and cancelling restores the game.
  const {
    conflicts: pending,
    assets: assetsPending,
    assetsApplied,
  } = interruptedUpdate(state.git, active?.action);
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
      (pending || assetsPending) &&
      ["version_continue", "version_abort"].includes(
        session.latest.action || "",
      )
    )
      ? session.latest
      : undefined;
  const layout = stagedLayout(session.stage);
  // The comparison the update applied, for the text it brought in.
  const compared = session.current.find(
    (job) => job.action === "version_preview" && job.status === "complete",
  )?.result;
  const guidedState =
    application.snapshot?.guided?.projectId === project.id
      ? application.snapshot.guided
      : undefined;
  const updateTasks =
    done && guided && compared
      ? guidedUpdateTasks(
          compared,
          new Map(guidedState?.files.map((file) => [file.name, file.group])),
          (name, phase) => {
            // A file the update changed holds its new text once reloaded;
            // until then its lines are the comparison's.
            if (!guidedState || guidedState.sourceStatus.changed.includes(name))
              return undefined;
            const { done, total, running } = fileLines(
              guidedState,
              phase,
              name,
            );
            return total === null || running ? undefined : total - done;
          },
        )
      : [];
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
        (!choosing || action.key === name) &&
        // A cancelled update's comparison no longer applies.
        !(session.aborted && name === "version_preview")
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
    : assetsApplied
      ? "Assets to copy"
      : assetsPending
        ? "Update stopped"
        : failedStep
          ? sentence(failedStep.status)
          : "";
  return (
    <div className="version-panel">
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
          <p>Checkpoints and game updates start once the game is set up.</p>
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
        <Section
          title={
            pending || assetsApplied
              ? "Finish the interrupted update"
              : "Cancel the stopped update"
          }
        >
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
          ) : assetsApplied ? (
            <>
              <p>
                The translation has the update’s files, but the images, sounds
                and other assets it brings still need copying into the game.
              </p>
              <ActionSlot target={actionTarget}>
                {control(
                  "version_continue",
                  "Copy assets & finish",
                  {},
                  false,
                  true,
                )}
              </ActionSlot>
            </>
          ) : (
            <>
              <p>
                The update stopped before it reached the translation. Cancel it
                to go back
                {state.git?.translation_version
                  ? ` to version ${state.git.translation_version}`
                  : ""}
                , then apply it again.
              </p>
              <ActionSlot target={actionTarget}>
                {control("version_abort", "Cancel update", {}, false, true)}
              </ActionSlot>
            </>
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
        <Section title="Translate the new text">
          {guided ? (
            <>
              <p>
                {compared && textChanges(compared)
                  ? `${textSummary(textChanges(compared)!) || "No new text"}. `
                  : ""}
                Each task opens with the files the update changed selected.
                Files you translated before read Outdated there, and Reload from
                game brings in their new text; lines that kept their translation
                aren’t translated again.
              </p>
              {updateTasks.length ? (
                <ActionList>
                  {updateTasks.map((task) => (
                    <ActionRow
                      key={task.task}
                      label={
                        <>
                          <strong>{task.title}</strong>
                          <small>
                            {[
                              selectionNames(task.files),
                              task.lines &&
                                `${task.lines.toLocaleString()} ${task.lines === 1 ? "line" : "lines"} to translate`,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </small>
                        </>
                      }
                    >
                      <Button
                        disabled={!openTask}
                        onClick={() =>
                          task.task === "database" || task.task === "dialogue"
                            ? openFiles?.(task.task, task.files)
                            : openTask?.("translate", task.task)
                        }
                      >
                        Open {task.title}
                      </Button>
                    </ActionRow>
                  ))}
                </ActionList>
              ) : (
                <p className="muted">
                  The update changed no files these tasks translate.
                </p>
              )}
            </>
          ) : (
            <p>
              Your coding assistant translates what the update added or changed
              and keeps the translations that still apply.
            </p>
          )}
          <ActionSlot target={actionTarget}>
            {!guided && (
              <ActionControl
                label="Copy post-update task"
                variant="primary"
                disabled={disabled}
                pending={action.busy && action.key === "copy-update"}
                pendingText="Copying…"
                error={action.key === "copy-update" ? action.error : ""}
                notice={action.key === "copy-update" ? action.notice : ""}
                onClick={() =>
                  action.run(
                    async () =>
                      window.dazedtl.copyText(
                        (await api.translation.updateTask(project.id)).prompt,
                      ),
                    "Task copied. Run it in your coding assistant.",
                    "copy-update",
                  )
                }
              />
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
              false,
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
        <>
          {aborted && (
            <p className="muted">
              The update was canceled. Choose another release when you’re ready.
            </p>
          )}
          <ActionSlot target={actionTarget}>
            <Button
              variant="primary"
              disabled={disabled}
              title="Bring in the developer’s new version or patch; your translation carries over."
              onClick={chooseNew}
            >
              Start game update
            </Button>
          </ActionSlot>
        </>
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
