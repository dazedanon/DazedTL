import type {
  FullEstimate,
  FullEstimateTask,
  FullEstimateTaskProgress,
} from "../../api/contracts";
import { useRemaining, useSecond } from "../../state/useWorkTime";
import { StatusPanel } from "../../ui/StatusPanel";
import { StepProgress } from "../../ui/StepProgress";
import type { DisplayState } from "../../ui/displayStatus";
import {
  formatClock,
  formatDuration,
  formatRemaining,
} from "../../ui/workTime";
import { approximateClaudeInput } from "./TranslationReview";

const taskTitles: Record<FullEstimateTask["phase"], string> = {
  database: "Database files",
  dialogue: "Maps & events",
  advanced: "Other event text",
};

/** Whole dollars and cents; a cost below a cent still shows it is not free. */
export function cost(value: number) {
  if (value > 0 && value < 0.01) return "<$0.01";
  return (
    "$" +
    value.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

/** The whole game's total in one mode, from each task's estimate. */
export function estimateTotal(
  tasks: FullEstimateTask[],
  key: "batchCost" | "liveCost",
) {
  return tasks.reduce((sum, task) => sum + task[key], 0);
}

/** The most a task's Batch costs, with no cached instruction reused. */
const batchMost = (task: FullEstimateTask) =>
  task.batchMaxCost ?? task.batchCost;

/** A cost that may be a range, from full reuse of cached instructions to none. */
const costRange = (low: number, high: number) =>
  high > low ? `${cost(low)}–${cost(high)}` : cost(low);

const help =
  "Estimates every task that uses your API key, over all its files: Database files, Maps & events and Other event text. Names & glossary, Plugin files, Images and Text QA use your assistant's plan instead. Estimating is free and translates nothing; for Claude models it uses Anthropic's free token count.";

/** What a working task does now: its files and the time they still need. */
function TaskActivity({
  task,
  started,
  now,
}: {
  task: FullEstimateTaskProgress;
  started: string | null;
  now: number;
}) {
  const counted =
    task.state === "estimating" && task.current > 0 && task.total > 0
      ? task
      : undefined;
  const remaining = useRemaining(`${started}:${task.phase}`, counted, now);
  if (task.state === "counting") return "Counting Claude tokens";
  if (!counted) return "Starting";
  return (
    `${counted.current.toLocaleString()} of ${counted.total.toLocaleString()} files` +
    (remaining === undefined ? "" : ` · ${formatRemaining(remaining)}`)
  );
}

/**
 * Context's estimate of what translating the game's text costs, task by task,
 * in the translation mode chosen now: one estimate prices both.
 */
export function CostEstimate({
  value,
  mode,
}: {
  value: FullEstimate;
  mode: string;
}) {
  const result = value.result;
  const working = value.status === "working";
  const now = useSecond(working);
  const progress = working ? value.progress : null;
  const state: DisplayState = working
    ? "working"
    : !result
      ? value.status === "failed"
        ? "blocked"
        : "not_started"
      : value.current
        ? "done"
        : "outdated";
  const batch = mode === "batch" && !!result?.batchSupported;
  const tasks = result?.tasks ?? [];
  const batchLow = estimateTotal(tasks, "batchCost");
  const batchHigh = tasks.reduce((sum, task) => sum + batchMost(task), 0);
  const total = batch
    ? costRange(batchLow, batchHigh)
    : cost(estimateTotal(tasks, "liveCost"));
  const other = batch
    ? `Live would be about ${cost(estimateTotal(tasks, "liveCost"))}.`
    : result?.batchSupported
      ? `Batch would be about ${costRange(batchLow, batchHigh)}.`
      : "";
  const notes = [
    batch &&
      batchHigh > batchLow &&
      "The provider charges less for instructions it reuses, but a Batch sends its requests together, so it may reuse few of them. The higher figure reuses none.",
    tasks.some((task) => task.approximateInput) && approximateClaudeInput,
    tasks.some((task) => task.unestimatedThinking) &&
      "This model's thinking tokens are billed as output and are not included.",
    "Not included: speaker names the glossary lacks, Comparisons and retries of refused requests.",
  ].filter(Boolean);
  return (
    <StatusPanel
      title="Translation cost"
      state={state}
      progress={
        working
          ? value.stopping
            ? "Stopping…"
            : value.started
              ? `${formatClock((now - Date.parse(value.started)) / 1000)} elapsed`
              : undefined
          : result
            ? [
                result.model,
                batch ? "Batch" : "Live",
                // How long the next estimate may take.
                value.took !== null &&
                  value.took >= 1 &&
                  `took ${formatDuration(value.took)}`,
              ]
                .filter(Boolean)
                .join(" · ")
            : undefined
      }
      help={help}
      description={
        state === "outdated"
          ? "The guidance, source choices, game files, model or DazedTL itself changed since this estimate."
          : !result && !working
            ? "Estimate every Translate task that uses your API key, over all its files."
            : undefined
      }
    >
      {!!progress?.tasks.length && (
        <div className="status-panel-body">
          <StepProgress
            label="Estimate tasks"
            steps={progress.tasks.map((task, index) => {
              // Copying the game's text comes before every task, so it
              // shows on the first one.
              const copying = progress.copying && index === 0;
              const active =
                copying || !["waiting", "done"].includes(task.state);
              return {
                id: task.phase,
                label: taskTitles[task.phase],
                state:
                  task.state === "done" ? "done" : active ? "current" : "next",
                // Every task keeps its detail line, so nothing moves.
                detail: copying ? (
                  "Copying the game's text"
                ) : task.state === "done" &&
                  task.took !== null &&
                  task.took >= 0.5 ? (
                  formatDuration(task.took)
                ) : active ? (
                  <TaskActivity task={task} started={value.started} now={now} />
                ) : (
                  "\u00a0"
                ),
                fraction: !active
                  ? undefined
                  : task.state === "counting"
                    ? 1
                    : task.state === "estimating"
                      ? task.current / task.total
                      : 0,
              };
            })}
          />
        </div>
      )}
      {result && (
        <div className="status-panel-body cost-estimate">
          <div className="translation-cost-total">
            <span>Estimated {batch ? "Batch" : "Live"} cost</span>
            <strong>{total}</strong>
            <small>
              {other && `${other} `}Final cost depends on actual usage.
            </small>
          </div>
          <table className="cost-estimate-tasks">
            <thead>
              <tr>
                <th scope="col">Task</th>
                <th scope="col">Input tokens</th>
                <th scope="col">Cost</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.phase}>
                  <th scope="row">{taskTitles[task.phase]}</th>
                  {/* Live-only connections count tokens, not requests. */}
                  {task.noSources || !task.inputTokens ? (
                    <td colSpan={2}>
                      {task.noSources
                        ? "No sources chosen"
                        : "Nothing to translate"}
                    </td>
                  ) : (
                    <>
                      <td>{task.inputTokens.toLocaleString()}</td>
                      <td>
                        {batch
                          ? costRange(task.batchCost, batchMost(task))
                          : cost(task.liveCost)}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="cost-estimate-notes">
            {notes.map((note) => (
              <p key={String(note)}>{note}</p>
            ))}
          </div>
        </div>
      )}
    </StatusPanel>
  );
}
