/** Translate: phased runs, event text investigation and source choices. */
import type { ReactNode } from "react";
import { api } from "../../../../api/client";
import { flushDrafts } from "../../../../state/leaveGuards";
import { ActionControl } from "../../../../ui/ActionControl";
import { Button } from "../../../../ui/Button";
import { Message } from "../../../../ui/Feedback";
import { EventTextSources } from "../../EventTextSources";
import { TranslateWorkspace } from "../../TranslateWorkspace";
import { nothingToTranslate, sourceErrors } from "../../eventTextSelection";
import {
  activeRun,
  completeForSelection,
  estimateEmpty,
  needsSubmissionReview,
  phaseRun,
  translationStopLabel,
  unsettledBatches,
} from "../../translationView";
import { actionKey, fileCount } from "../model";
import { selectionNames } from "../../../../ui/displayText";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import { sinceLabel } from "../../../assistant/assistantTasks";
import {
  AssistantTask,
  type AssistantTaskState,
} from "../../../../ui/AssistantTask";

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
  // A file a Live run is still translating has only partial output to apply.
  const applyFiles = selectedNames.filter(
    (name) =>
      state.readiness.outputs.includes(name) &&
      !(
        activeRun(current) &&
        current?.mode !== "batch" &&
        current?.files?.includes(name)
      ),
  );
  const noRemainingWork = estimateEmpty(quote);

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
    (action.busy &&
      ["translate:prepare", actionKey("start", { mode, phase })].includes(
        action.key,
      ));
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
      {phase === "advanced" && (
        <>
          <p>
            {enabledCodes.length}{" "}
            {enabledCodes.length === 1 ? "source" : "sources"} enabled ·{" "}
            {advancedReady ? "Coverage reviewed" : "Source review needed"}
          </p>
          <Button
            variant="link"
            disabled={disabled || locked}
            onClick={() => stepTask("sources")}
          >
            Review source choices
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
        ? "Checking the selected files · please wait"
        : current?.approval
          ? "Awaiting your cost approval"
          : activeRun(current)
            ? current!.message
            : current?.temporary &&
                ["failed", "interrupted", "stopped"].includes(current.status)
              ? current.message ||
                "Preparation did not finish. Click Translate to try again."
              : pendingBatches.some(needsSubmissionReview)
                ? "The last Batch could not be confirmed as sent. Check it in Run history before translating these files again."
                : pendingBatches.length
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
        {([
          "translate:prepare",
          "run:answer:false",
          "run:stop",
          "run:finished",
        ].includes(action.key) &&
          action.notice) ||
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
          {},
          !baseline ||
            !!state.collectionError ||
            applyFiles.some((name) => changed.includes(name)),
          "default",
          applyFiles,
        )}
    </>
  );
  return {
    content,
    secondary,
    action: (
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
    next: advance(undefined, undefined, "quiet"),
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

export function auditView(w: GuidedWorkspace): TaskView {
  const {
    state,
    eventFiles,
    disabled,
    stepTask,
    skipEventText,
    copyTask,
    fileSummary,
    handoff,
  } = w;
  const investigating = handoff("event_text");
  // A dismissed task no longer waits for its findings.
  const status =
    investigating.dismissed && state.eventText.status === "waiting"
      ? "missing"
      : state.eventText.status;
  // Saved findings wait for your source review until accepted.
  const reviewed = status === "ready" && state.eventText.accepted;
  const taskState: AssistantTaskState = reviewed
    ? "done"
    : (
        {
          missing: "not_started",
          waiting: "waiting",
          ready: "needs_review",
          stale: "outdated",
          invalid: "blocked",
        } as const
      )[status];
  let content: ReactNode;
  content = (
    <>
      {fileSummary(
        eventFiles.map((file) => file.name),
        "dialogue",
      )}
      <AssistantTask
        state={taskState}
        progress={
          status === "waiting" ? sinceLabel(investigating.since) : undefined
        }
        description={
          status === "missing"
            ? "Your assistant checks every affected use and internal reference, and returns the commands and argument keys it finds as evidence."
            : status === "waiting"
              ? "Findings appear here as your assistant saves them."
              : reviewed
                ? "Your source choices are saved for these findings."
                : state.eventText.message
        }
        help="The task only saves findings. It does not enable sources, edit engine code, start translation or call providers."
        results={[
          {
            id: "findings",
            title: "Source findings",
            state: taskState,
            detail: reviewed
              ? "Coverage evidence for each source."
              : status === "ready"
                ? "Coverage evidence for each source, ready to review."
                : "Which event codes, plugin commands and scripts carry player text.",
          },
        ]}
      />
    </>
  );
  // Investigating comes first; manual review and skipping stay available.
  const ready = state.eventText.status === "ready";
  return {
    content,
    secondary: (
      <Button variant="quiet" disabled={disabled} onClick={skipEventText}>
        Skip event codes
      </Button>
    ),
    action:
      !ready && copyTask("advanced", "Copy investigation task", "primary"),
    // The source choices come next, with findings or reviewed by hand.
    next: (
      <Button
        variant={ready ? "primary" : "quiet"}
        disabled={disabled}
        onClick={() => stepTask("sources")}
      >
        {ready ? "Review findings & source choices" : "Review sources manually"}
      </Button>
    ),
    heading: {
      title: "Investigate sources",
      description:
        "Your assistant checks which event codes, plugin commands and scripts carry player text.",
    },
  };
}

export function sourcesView(w: GuidedWorkspace): TaskView {
  const {
    state,
    action,
    values,
    eventFiles,
    enabledCodes,
    edit,
    disabled,
    stepTask,
    openSourcePicker,
    reviewSources,
    confirmNoEventText,
    skipEventText,
    chooseFiles,
    feedback,
  } = w;
  let content: ReactNode;
  content = (
    <>
      <div className="translation-source-toolbar">
        <span>
          {fileCount(eventFiles.length)} selected
          {!!eventFiles.length &&
            ` · ${selectionNames(eventFiles.map((file) => file.name))}`}
        </span>
        <Button
          variant="quiet"
          disabled={disabled}
          onClick={() => chooseFiles("dialogue")}
        >
          Choose files
        </Button>
      </div>
      <EventTextSources
        state={state.eventText}
        values={values.engine_options}
        disabled={disabled}
        change={(key, value) =>
          edit("engine_options", { ...values.engine_options, [key]: value })
        }
        openPicker={openSourcePicker}
        recommendationFeedback={feedback("event-text:recommendations")}
        recommendations={() =>
          action.run(
            async () => {
              edit("engine_options", {
                ...values.engine_options,
                ...state.eventText.recommended,
              });
              await flushDrafts();
            },
            "Recommendations staged.",
            "event-text:recommendations",
          )
        }
      />
    </>
  );
  const review = !!enabledCodes.length && (
    <Button
      variant="primary"
      pending={action.busy && action.key === "event-text:review"}
      disabled={
        disabled ||
        !!sourceErrors(state.eventText, values.engine_options).length ||
        !eventFiles.length
      }
      onClick={reviewSources}
    >
      Review source choices
    </Button>
  );
  const findingsReady = state.eventText.status === "ready";
  const nothing = nothingToTranslate(state.eventText, values.engine_options);
  return {
    content,
    action: enabledCodes.length
      ? review
      : findingsReady &&
        !nothing && (
          <ActionControl
            variant="primary"
            label="Confirm nothing to translate"
            disabled={disabled}
            {...feedback("event-text:none", "Saving…")}
            onClick={confirmNoEventText}
          />
        ),
    next: enabledCodes.length ? (
      <Button
        variant="quiet"
        disabled={disabled}
        onClick={() => stepTask("advanced-run")}
      >
        Continue to translation
      </Button>
    ) : nothing ? (
      <Button variant="primary" disabled={disabled} onClick={skipEventText}>
        {state.comparisons.status !== "not_needed"
          ? "Review comparisons"
          : "Continue to plugin files"}
      </Button>
    ) : (
      !findingsReady && (
        <Button variant="primary" disabled={disabled} onClick={skipEventText}>
          Skip event codes
        </Button>
      )
    ),
    heading: {
      title: "Source choices",
      description: "Enable only the sources the investigation confirmed.",
    },
  };
}
