import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type {
  TranslationJob,
  TranslationOptions,
  TranslationProgress,
  TranslationState,
} from "../../api/contracts";
import { flushDrafts } from "../../state/leaveGuards";
import { useMinute } from "../../state/useMinute";
import type { useAction } from "../../state/useAction";
import { ActionControl } from "../../ui/ActionControl";
import { AssistantTask, type AssistantTaskState } from "../../ui/AssistantTask";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Feedback } from "../../ui/Feedback";
import { displayLabels, type DisplayState } from "../../ui/displayStatus";
import { timeAgo } from "../../ui/displayText";
import { JobStatus } from "../../ui/JobStatus";
import { StatusPanel } from "../../ui/StatusPanel";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";
import { StepProgress, type StepState } from "../../ui/StepProgress";
import { TranslationCost } from "../guided/TranslationReview";
import type { ProjectLink } from "../guided/workspace/model";
import {
  approvalUntold,
  attemptJobs,
  awaitingQuote,
  latestApiRun,
} from "./apiRun";
import { modeLabels } from "./OptionsPanel";
import { StartOver } from "./StartOver";

/** The assistant's phases, in the order the starting prompt works through. */
const phases = [
  { id: "preparation", label: "Preparation" },
  { id: "extraction", label: "Extraction" },
  { id: "translation", label: "Translation" },
  { id: "injection", label: "Injection" },
  { id: "qa", label: "QA" },
  { id: "patch", label: "Patch" },
];
const phaseSteps: Record<string, { state: StepState; detail?: string }> = {
  complete: { state: "done" },
  active: { state: "current" },
  blocked: { state: "blocked", detail: displayLabels.blocked },
  out_of_scope: { state: "next", detail: displayLabels.skipped },
};
/** The assistant reports at least every 10 minutes while it works. */
const QUIET_MINUTES = 20;
const money = (value: number) => "$" + value.toFixed(2);

function taskState(
  progress: TranslationProgress | null,
  started: boolean,
): AssistantTaskState {
  if (!progress?.updated_at) return started ? "waiting" : "not_started";
  if (progress.blocker) return "blocked";
  return Object.values(progress.phases).every((phase) =>
    ["complete", "out_of_scope"].includes(phase),
  )
    ? "done"
    : "waiting";
}

/**
 * Where the assistant's run stands, from its saved reports: what it needs,
 * which phase it is in, what is translated, and any API run the app holds.
 */
export function ProgressPanel({
  state,
  options,
  action,
  openProject,
  showOptions,
  resume,
}: {
  state: TranslationState;
  options: TranslationOptions;
  action: ReturnType<typeof useAction>;
  openProject: ProjectLink;
  showOptions: () => void;
  /** Copies the prompt that hands the work back to the assistant. */
  resume: ReactNode;
}) {
  const now = useMinute();
  const [report, setReport] = useState(false);
  const progress = state.progress;
  const reported = !!progress?.updated_at;
  // The latest sign of the assistant is its use of the helper, which also
  // sends its reports. An API run republishes the report while it works, so
  // the report's time stands in only for projects from before DazedTL noted
  // helper use.
  const activity = state.assistantSeenAt || progress?.updated_at || undefined;
  const status = taskState(progress, !!activity);
  const text = progress?.metrics.text;
  const images = progress?.metrics.images;
  const attempt = attemptJobs(state);
  const run = latestApiRun(attempt);
  const untold = approvalUntold(run, state.assistantSeenAt);
  // The API run's approval reminder already says to paste the prompt.
  const quiet =
    status === "waiting" &&
    !untold &&
    now - new Date(activity!).getTime() > QUIET_MINUTES * 60_000;
  const operation = attempt.find(
    (job) =>
      job.kind === "operation" &&
      job.action !== "start_over" &&
      ["running", "waiting"].includes(job.status),
  );
  const total = text && (text.total ?? text.discovered);
  return (
    <>
      <p className="translation-mode-summary">
        <span>
          {modeLabels[options.mode]}
          {options.mode !== "agent" &&
            state.connection?.model &&
            ` · ${state.connection.name} · ${state.connection.model}`}
        </span>
        <Button variant="link" onClick={showOptions}>
          Change
        </Button>
      </p>
      <AssistantTask
        state={status}
        progress={activity && "last active " + timeAgo(activity, now)}
        description={
          progress?.blocker ||
          progress?.next_action ||
          // A report without a next step leaves the phases to speak.
          (reported
            ? undefined
            : activity
              ? "Your assistant has started preparing the game. Its first report will appear here."
              : "Copy the starting prompt into your coding assistant. It backs up the game, extracts and translates the text and builds a patch on its own; its reports appear here.")
        }
        help="These are your assistant's saved reports and the last time it used DazedTL. Neither shows that its session is still running, and finished text doesn't mean the game has been checked."
      >
        {status === "blocked" && (
          <Notice tone="warning">
            <span>
              <strong>Needs you:</strong>{" "}
              {progress!.next_action ||
                "answer your assistant, then paste the prompt to resume."}
            </span>
          </Notice>
        )}
        {quiet && (
          <Notice>
            If your assistant has stopped, for example at a usage limit, paste
            the prompt into a new session; it picks up the saved work.
          </Notice>
        )}
        <StepProgress
          label="Assistant phases"
          steps={phases.map((phase) => ({
            ...phase,
            ...(phaseSteps[
              reported
                ? progress.phases[phase.id]
                : activity && phase.id === "preparation"
                  ? "active"
                  : ""
            ] || { state: "next" }),
          }))}
        />
        {!!(text?.translated || text?.reviewed || images?.translated) && (
          <p className="translation-metrics">
            {!!text?.translated && (
              <span>
                <strong>{text.translated.toLocaleString()}</strong>
                {total == null
                  ? " lines translated"
                  : ` of ${total.toLocaleString()} lines translated`}
                {text.total === null && (
                  <span className="muted"> (count not final)</span>
                )}
              </span>
            )}
            {!!text?.reviewed && (
              <span>
                <strong>{text.reviewed.toLocaleString()}</strong> checked
                against the Japanese
              </span>
            )}
            {options.include_images && !!images?.translated && (
              <span>
                <strong>{images.translated.toLocaleString()}</strong>
                {images.total === null
                  ? " images translated"
                  : ` of ${images.total.toLocaleString()} images translated`}
              </span>
            )}
          </p>
        )}
        {operation && <JobStatus job={operation} />}
      </AssistantTask>
      {(options.mode !== "agent" || run) && (
        <ApiRun
          run={run}
          state={state}
          action={action}
          untold={untold}
          resume={resume}
        />
      )}
      <div className="lens-project-links">
        {state.statusText && (
          <Button variant="link" onClick={() => setReport(true)}>
            Assistant&apos;s report
          </Button>
        )}
        <Button variant="link" onClick={() => openProject("history")}>
          Run history
        </Button>
        <Button variant="link" onClick={() => openProject("backups")}>
          Backups
        </Button>
        <Button variant="link" onClick={() => openProject("versions")}>
          Game updates
        </Button>
        <StartOver
          state={state}
          activity={activity}
          available={!!(reported || state.assistantSeenAt || attempt.length)}
        />
      </div>
      {report && (
        <Modal
          label="Assistant's report"
          size="lg"
          onDismiss={() => setReport(false)}
        >
          <DialogHeader
            title="Assistant's report"
            description="The detailed notes your assistant keeps in status.md."
            onClose={() => setReport(false)}
          />
          <DialogBody>
            <pre className="translation-report">{state.statusText}</pre>
          </DialogBody>
        </Modal>
      )}
    </>
  );
}

/** How a saved API run reads in the shared status words. */
const runStates: Record<string, DisplayState> = {
  ready: "not_started",
  running: "working",
  waiting: "waiting",
  // A paused run waits to be resumed; its message says it was paused.
  stopped: "waiting",
  canceled: "waiting",
  complete: "done",
};

/** The latest API run the app holds for the assistant, with its spending. */
function ApiRun({
  run,
  state,
  action,
  untold,
  resume,
}: {
  run: TranslationJob | undefined;
  state: TranslationState;
  action: ReturnType<typeof useAction>;
  untold: boolean;
  resume: ReactNode;
}) {
  if (!run)
    return (
      <StatusPanel
        title="API run"
        state="not_started"
        description="Your assistant asks you to approve its estimate before anything is sent."
      />
    );
  const mode = run.mode === "live" ? "live" : "batch";
  const charged = run.usage.openrouter_cost;
  const quote = awaitingQuote(run);
  const reminder = ["running", "waiting"].includes(run.status)
    ? "tell your assistant you approved this run here, so it waits for the results and carries on."
    : run.status === "complete"
      ? "tell your assistant this run has finished, so it carries on."
      : "tell your assistant you approved this run here, so it checks the run and carries on.";
  const pause = ["running", "waiting"].includes(run.status) && (
    <ActionControl
      label={run.stop_requested ? "Pausing" : "Pause at the next safe point"}
      disabled={action.busy || run.stop_requested}
      pending={action.busy && action.key === "pause"}
      pendingText="Pausing…"
      error={action.key === "pause" ? action.error : ""}
      onClick={() =>
        void action.run(
          () => api.translation.stop(state.projectId, run.id),
          "",
          "pause",
        )
      }
    />
  );
  return (
    <StatusPanel
      title="API run"
      state={quote ? "needs_review" : runStates[run.status] || "blocked"}
      progress={modeLabels[mode]}
      description={
        quote
          ? "Nothing is sent until you approve this estimate, here or in your assistant's conversation."
          : run.message
      }
    >
      <div className="status-panel-body">
        {quote ? (
          <>
            <TranslationCost
              value={{
                requests: quote.requests,
                input_tokens: quote.input_tokens,
                output_tokens: quote.output_tokens,
                [mode === "batch" ? "batch_cost" : "live_cost"]: quote.cost,
              }}
              mode={mode}
            />
            {mode === "batch" && quote.provider === "openrouter" && (
              <Notice>
                OpenRouter uses a 24-hour window, and a submitted Batch cannot
                be canceled through this app.
              </Notice>
            )}
            <ActionControl
              variant="primary"
              label={
                mode === "batch"
                  ? "Approve and submit Batch"
                  : "Approve and start Live"
              }
              disabled={action.busy || state.active || !state.providerEnabled}
              disabledReason={
                !state.providerEnabled
                  ? "Provider execution is off for this launch."
                  : state.active
                    ? "Wait for the current work to finish."
                    : ""
              }
              pending={action.busy && action.key === "approve"}
              pendingText={mode === "batch" ? "Submitting…" : "Starting…"}
              error={action.key === "approve" ? action.error : ""}
              onClick={() =>
                void action.run(
                  async () => {
                    await flushDrafts();
                    await api.translation.start(
                      state.projectId,
                      run.id,
                      run.approval_token,
                    );
                  },
                  "",
                  "approve",
                )
              }
            />
          </>
        ) : (
          <>
            <p className="translation-metrics">
              <span>
                <strong>{run.accepted_units.toLocaleString()}</strong> of{" "}
                {run.units.toLocaleString()} lines saved
              </span>
              {run.quote && <span>Estimate {money(run.quote.cost)}</span>}
              {charged != null && <span>Charged {money(charged)}</span>}
            </p>
            {/* An approval can be saved and the run still refuse to start;
                the button that reported it is gone by then. */}
            {action.key === "approve" && action.error && (
              <Feedback error={action.error} />
            )}
            {pause}
            {untold && (
              <>
                <Notice tone="warning">
                  <span>
                    <strong>Needs you:</strong> {reminder} If its session has
                    ended, paste the prompt into a new one.
                  </span>
                </Notice>
                {resume}
              </>
            )}
          </>
        )}
      </div>
    </StatusPanel>
  );
}
