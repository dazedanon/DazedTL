/** Translate: phased runs, event text investigation and source choices. */
import type { ReactNode } from "react";
import { api } from "../../../../api/client";
import { flushDrafts } from "../../../../state/leaveGuards";
import { ActionControl } from "../../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { Message } from "../../../../ui/Feedback";
import { EventTextSources } from "../../EventTextSources";
import { TranslateWorkspace } from "../../TranslateWorkspace";
import { sourceErrors } from "../../eventTextSelection";
import {
  activeRun,
  completeForSelection,
  estimateEmpty,
  phaseRun,
  translationStopLabel,
  unsettledBatches,
} from "../../translationView";
import { actionKey, fileCount } from "../model";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function phaseView(w: GuidedWorkspace): TaskView {
  const {
    project,
    state,
    settings,
    action,
    values,
    setPanel,
    setSubmission,
    setComparisonReview,
    setComparisonsAccepted,
    setHistory,
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
  let content: ReactNode, primary: ReactNode, actionContext: ReactNode;
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
  const applyFiles = selectedNames.filter((name) =>
    state.readiness.outputs.includes(name),
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
      history={() => setHistory("all")}
      inspect={inspect}
      inspectedFile={inspectionTarget?.file}
      fileActions={task(
        "refresh_sources",
        "Resync",
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
            {enabledCodes.length} sources enabled ·{" "}
            {advancedReady ? "Coverage reviewed" : "Source review needed"}
          </p>
          <Button
            variant="quiet"
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
            <Button onClick={() => setPanel("backups")}>
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
      ? "Complete Prepare before translating."
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
        {(["translate:prepare", "run:answer:false", "run:stop"].includes(
          action.key,
        ) &&
          action.notice) ||
          guidance}
      </small>
    </div>
  );
  primary = (
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
      <Button
        variant="primary"
        pending={preparing}
        disabled={
          disabled || prerequisites || !state.provider.ready || !paidModeReady
        }
        onClick={translateSelected}
      >
        Translate
      </Button>
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
  return { content, primary, actionContext };
}

export function auditView(w: GuidedWorkspace): TaskView {
  const {
    state,
    application,
    action,
    eventFiles,
    disabled,
    stepTask,
    skipEventText,
    feedback,
    copyTask,
    fileSummary,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  content = (
    <>
      {fileSummary(eventFiles.length, "dialogue")}
      <ActionList>
        <ActionRow
          label={
            <>
              <strong>Investigate source coverage</strong>
              <small>
                Check every affected use and internal reference before selecting
                variable IDs, registered handlers or patterns. Found commands
                and argument keys return as evidence.
              </small>
            </>
          }
        >
          {copyTask("advanced", "Copy investigation task")}
        </ActionRow>
      </ActionList>
      <p className="muted">{state.eventText.message}</p>
      <p className="muted">
        The copied task saves findings. It does not enable controls, edit engine
        code, start translation, or call providers.
      </p>
      <ActionControl
        label="Refresh findings"
        disabled={disabled}
        {...feedback("event-text:refresh", "Reading saved findings…")}
        onClick={() =>
          action.run(
            () => application.refresh(),
            "Findings refreshed.",
            "event-text:refresh",
          )
        }
      />
    </>
  );
  primary = (
    <Button
      variant="primary"
      disabled={disabled}
      onClick={() => stepTask("sources")}
    >
      {state.eventText.status === "ready"
        ? "Review findings & source choices"
        : "Review sources manually"}
    </Button>
  );
  secondary = (
    <Button disabled={disabled} onClick={skipEventText}>
      Continue without other event text
    </Button>
  );
  return { content, primary, secondary };
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
    skipEventText,
    chooseFiles,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  content = (
    <>
      <div className="translation-source-toolbar">
        <span>{fileCount(eventFiles.length)} selected</span>
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
        recommendations={() =>
          action.run(
            async () => {
              edit("engine_options", {
                ...values.engine_options,
                ...state.eventText.recommended,
              });
              await flushDrafts();
            },
            "Recommendations staged. Review source choices before continuing.",
            "event-text:recommendations",
          )
        }
      />
    </>
  );
  primary = enabledCodes.length ? (
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
  ) : (
    <Button variant="primary" disabled={disabled} onClick={skipEventText}>
      Continue without other event text
    </Button>
  );
  secondary = enabledCodes.length ? (
    <Button disabled={disabled} onClick={() => stepTask("advanced-run")}>
      Continue to translation
    </Button>
  ) : null;
  return { content, primary, secondary };
}
