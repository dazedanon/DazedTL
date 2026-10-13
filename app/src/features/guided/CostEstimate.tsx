import type { FullEstimate, FullEstimateTask } from "../../api/contracts";
import { StatusPanel } from "../../ui/StatusPanel";
import type { DisplayState } from "../../ui/displayStatus";
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
  key: "batchCost" | "batchNocacheCost" | "liveCost",
) {
  return tasks.reduce((sum, task) => sum + task[key], 0);
}

const help =
  "Estimates every task that uses your API key, over all its files: Database files, Maps & events and Other event text. Names & glossary, Plugin files, Images and Text QA use your assistant's plan instead. Estimating is free and translates nothing; for Claude models it uses Anthropic's free token count.";

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
  const total = estimateTotal(tasks, batch ? "batchCost" : "liveCost");
  const other = batch
    ? `Live would be about ${cost(estimateTotal(tasks, "liveCost"))}.`
    : result?.batchSupported
      ? `Batch would be about ${cost(estimateTotal(tasks, "batchCost"))}.`
      : "";
  const uncached = estimateTotal(tasks, "batchNocacheCost");
  const caching =
    batch && tasks.some((task) => task.promptCache) && uncached > total;
  const notes = [
    caching &&
      `With the provider's lower rate for repeated instructions; without it, about ${cost(uncached)}.`,
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
          ? value.message
          : result
            ? `${result.model} · ${batch ? "Batch" : "Live"}`
            : undefined
      }
      help={help}
      description={
        state === "outdated"
          ? "The guidance, source choices, game files or model changed since this estimate."
          : !result && !working
            ? "Estimate every Translate task that uses your API key, over all its files."
            : undefined
      }
    >
      {result && (
        <div className="status-panel-body cost-estimate">
          <div className="translation-cost-total">
            <span>Estimated {batch ? "Batch" : "Live"} cost</span>
            <strong>{cost(total)}</strong>
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
                      <td>{cost(batch ? task.batchCost : task.liveCost)}</td>
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
