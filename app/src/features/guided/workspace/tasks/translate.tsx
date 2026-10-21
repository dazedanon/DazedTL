/** Translate's phased runs, and the event text sources Context chooses for them. */
import type { ReactNode } from "react";
import { api } from "../../../../api/client";
import { Button } from "../../../../ui/Button";
import { Message } from "../../../../ui/Feedback";
import { RunFailure } from "../../RunFailure";
import { TranslateWorkspace } from "../../TranslateWorkspace";
import { nothingToTranslate } from "../../eventTextSelection";
import { historyWhen } from "../../historyView";
import {
  activeRun,
  completeForSelection,
  estimateEmpty,
  phaseRun,
  savedTranslations,
  translationStopLabel,
  unconfirmedSubmission,
  unsettledBatches,
} from "../../translationView";
import { actionKey, runNotices } from "../model";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function phaseView(w: GuidedWorkspace): TaskView {
  const {
    advance,
    project,
    state,
    settings,
    action,
    values,
    setPanel,
    setSubmission,
    setComparisonReview,
    setComparisonsAccepted,
    openProject,
    setRunHistory,
    inspectionTarget,
    preserved,
    baseline,
    changed,
    enabledCodes,
    advancedReady,
    mode,
    paidModeReady,
    phase,
    phaseFiles,
    currentEstimate,
    activeOperation,
    edit,
    translationFlow,
    disabled,
    stepTask,
    translateSelected,
    task,
    resyncPending,
    inspect,
  } = w;
  let content: ReactNode, actionContext: ReactNode;
  const selectedNames = phaseFiles.map((file) => file.name);
  const latest = phaseRun(state.runs, phase, selectedNames);
  const saved =
    state.phaseRuns[phase]?.id === latest?.id ? state.phaseRuns[phase] : latest;
  const current =
    saved && !state.sourceStatus.retired?.includes(saved.id)
      ? {
          ...saved,
          scopeComplete: completeForSelection(saved, selectedNames),
        }
      : undefined;
  const quote = currentEstimate(phase);
  const localEstimate = state.estimates[phase]?.job;
  const pendingBatches = unsettledBatches(state.runs, selectedNames);
  const locked =
    activeRun(current) ||
    activeRun(localEstimate) ||
    translationFlow.active ||
    !!pendingBatches.length;
  // A file a Live run is still translating has only partial output to apply,
  // and one no run translated has nothing to apply.
  const { outputs: translatedOutputs, applied: appliedOutputs } =
    savedTranslations(state);
  const applyFiles = selectedNames.filter(
    (name) =>
      translatedOutputs.includes(name) &&
      !(
        activeRun(current) &&
        current?.mode !== "batch" &&
        current?.files?.includes(name)
      ),
  );
  // The working copy holds whichever run saved last, even one from another
  // task, so a finished run that saved every file applies its own output.
  const ownRun =
    current &&
    !current.temporary &&
    current.status === "complete" &&
    ["batch", "translate"].includes(current.mode || "") &&
    applyFiles.length > 0 &&
    applyFiles.every((name) => current.availableOutputs?.includes(name))
      ? current
      : undefined;
  const noRemainingWork = estimateEmpty(quote);
  // Other event text whose chosen sources leave nothing has no run to start.
  const nothingLeft =
    phase === "advanced" &&
    nothingToTranslate(state.eventText, values.engine_options);
  // The latest attempt's failure shows on the task itself, not only in Run
  // history; an unconfirmed Batch also warns before anything is sent again.
  const unconfirmed = pendingBatches.find(unconfirmedSubmission);
  const failed =
    current && !current.temporary && current.status === "failed"
      ? current
      : undefined;
  // A newer run's outcome is not this Batch's, so name its Run history row.
  const earlier =
    unconfirmed &&
    state.runs.some(
      (run) =>
        run.logicalPhase === phase &&
        run.mode !== "estimate" &&
        !run.temporary &&
        (run.created || "") > (unconfirmed.created || ""),
    );
  const when = earlier ? historyWhen(unconfirmed.created) : "";
  // Provider progress changes an unconfirmed Batch's message, not its doubt.
  const failure = unconfirmed
    ? {
        run: unconfirmed.id,
        reason: "unconfirmed " + unconfirmed.process?.uncertain,
        message: `${earlier ? `An earlier Batch${when ? " from " + when : ""}` : "The last Batch"} could not be confirmed as sent, so it may still be at the provider. ${unconfirmed.message ? unconfirmed.message + " " : ""}Check Run history before translating these files again.`,
      }
    : failed && {
        run: failed.id,
        reason: "failed " + (failed.message || ""),
        message: `The last run failed. ${failed.message || "Run history shows why."}`,
      };

  const prerequisites =
    resyncPending ||
    !baseline ||
    !!changed.length ||
    !state.provider.model ||
    !phaseFiles.length ||
    (phase === "advanced" && !advancedReady) ||
    (phase === "variables" && state.comparisons.status !== "ready");
  const estimating = translationFlow.active;
  // The open dialog owns its result or approval; only its work is pending here.
  const preparing =
    translationFlow.pending ||
    (action.busy && action.key === actionKey("start", { mode, phase }));
  const stopLabel =
    estimating || current?.mode === "batch"
      ? null
      : translationStopLabel(current);
  // A Live run saves results until it ends; a new run would copy its partial
  // working files and drop the rest. Stop it or wait instead.
  const liveRunning = activeRun(current) && current?.mode !== "batch";
  content = (
    <TranslateWorkspace
      key={phase}
      state={state}
      phase={phase}
      values={values}
      run={current}
      estimate={localEstimate}
      currentEstimate={!!quote}
      disabled={disabled || resyncPending}
      locked={translationFlow.active}
      change={edit}
      settings={settings}
      options={() => setPanel("translation-context")}
      history={() => setRunHistory(phase)}
      inspect={inspect}
      inspectedFile={inspectionTarget?.file}
      fileActions={task(
        "refresh_sources",
        "Reload from game…",
        {},
        !preserved || !selectedNames.length || !!activeOperation,
        "default",
        selectedNames,
      )}
    >
      {!baseline && (
        <p className="translation-error">
          Preserve the original and save its version baseline before
          translating.
        </p>
      )}
      {!state.provider.enabled && (
        <p className="muted">
          Provider execution is disabled for this launch. Local estimates are
          available.
        </p>
      )}
      {!paidModeReady && (
        <Message message="This connection does not support Batch. Choose Live or a supported connection." />
      )}
      {failure && <RunFailure {...failure} />}
      {phase === "advanced" && (
        <>
          <p>
            {nothingLeft
              ? "Event text sources found no other event text to translate."
              : !enabledCodes.length
                ? "No source chosen yet."
                : `${enabledCodes.length} ${enabledCodes.length === 1 ? "source" : "sources"} enabled${advancedReady ? "" : " · Source choices need fixes"}`}
          </p>
          <Button
            variant="link"
            disabled={disabled || locked}
            onClick={() =>
              stepTask(enabledCodes.length || nothingLeft ? "sources" : "audit")
            }
          >
            {enabledCodes.length || nothingLeft
              ? "Edit source choices"
              : "Choose sources"}
          </Button>
        </>
      )}
      {phase === "variables" && (
        <>
          <p>{state.comparisons.message}</p>
          {state.comparisons.status === "recovery_needed" ? (
            <Button onClick={() => openProject("backups")}>
              Backups & recovery
            </Button>
          ) : (
            state.comparisons.matches > 0 && (
              <Button
                disabled={disabled || locked}
                onClick={() => {
                  setComparisonsAccepted(false);
                  setComparisonReview(true);
                }}
              >
                Review matching comparisons
              </Button>
            )
          )}
        </>
      )}
    </TranslateWorkspace>
  );
  const guidance = !selectedNames.length
    ? "Select files to translate."
    : !baseline
      ? "Set up the game before translating."
      : preparing
        ? "Estimating the cost · please wait"
        : current?.approval
          ? "Awaiting your cost approval"
          : activeRun(current)
            ? current!.message
            : current?.temporary &&
                ["failed", "interrupted", "stopped"].includes(current.status)
              ? current.message ||
                "Preparation did not finish. Click Translate to try again."
              : pendingBatches.some((run) => !unconfirmedSubmission(run))
                ? applyFiles.length
                  ? "Earlier Batches are available in Run history. You can apply saved output."
                  : "Earlier Batches are available in Run history. Translate starts a new estimate."
                : noRemainingWork
                  ? "Checked these files: no new API requests are needed."
                  : "Translate prepares an estimate for your approval.";
  actionContext = (
    <div className="translation-action-scope">
      <strong>
        {selectedNames.length} selected
        {applyFiles.length ? ` · ${applyFiles.length} saved` : ""}
      </strong>
      <small>
        {(runNotices.includes(action.key) && action.notice) ||
          translationFlow.notice ||
          guidance}
      </small>
    </div>
  );
  const secondary = (
    <>
      {current?.approval && (
        <Button disabled={disabled} onClick={() => setSubmission(current)}>
          Review cost
        </Button>
      )}
      {stopLabel && (
        <Button
          variant="quiet"
          disabled={disabled}
          pending={action.busy && action.key === "run:stop"}
          onClick={() =>
            action.run(
              () => api.stop(project.id, current!.id),
              "Stop requested. Saved work is retained.",
              "run:stop",
            )
          }
        >
          {stopLabel}
        </Button>
      )}
      {!!applyFiles.length &&
        task(
          "export_selected",
          `Apply (${applyFiles.length})`,
          ownRun ? { run_id: ownRun.id } : {},
          !baseline ||
            !!state.collectionError ||
            applyFiles.some((name) => changed.includes(name)) ||
            // The files' rows read Applied, so Apply has nothing to do.
            (applyFiles.every((name) => appliedOutputs.includes(name)) &&
              "Saved translations applied."),
          "default",
          applyFiles,
        )}
    </>
  );
  return {
    content,
    secondary,
    action: !nothingLeft && (
      <Button
        variant="primary"
        pending={preparing}
        disabled={
          disabled ||
          prerequisites ||
          liveRunning ||
          !state.provider.ready ||
          !paidModeReady
        }
        onClick={translateSelected}
      >
        Translate
      </Button>
    ),
    next: advance(undefined, undefined, nothingLeft ? "primary" : "quiet"),
    actionContext,
    heading:
      phase === "advanced"
        ? {
            title: "Translate event codes",
            description:
              "Translate the enabled sources in the selected event files.",
          }
        : phase === "variables"
          ? {
              title: "Update comparisons",
              description:
                "Update variable comparisons from the audited assignments.",
            }
          : undefined,
  };
}
