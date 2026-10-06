import type { Job, TranslationState, GuidedState } from "../../api/contracts";
import { Tabs } from "../../ui/Tabs";
import { batchInProgress } from "./batchView";
import { activeRun, phaseRun } from "./translationView";
import {
  historyDate,
  historyDay,
  historyMode,
  historyOutcome,
  historyPhase,
  type HistoryOutcome,
} from "./historyView";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleSlash,
  Clock3,
  FileCheck2,
  LoaderCircle,
  Pause,
  XCircle,
  CircleHelp,
} from "lucide-react";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { useMemo, useState } from "react";
import { Button } from "../../ui/Button";
import { ActionSlot } from "../../ui/ActionSlot";
import { HelpPopover } from "../../ui/HelpPopover";

export function operationSummary(job: Job): string {
  const result = job.result;
  if (!result) return "";
  if (typeof result.archive === "string")
    return `${Number(result.files || 0)} ${result.files === 1 ? "file" : "files"} reloaded from the game. Previous copies and outputs archived.`;
  if (typeof result.files === "number")
    return `${result.files} ${result.files === 1 ? "file" : "files"} saved.`;
  if (typeof result.changes_found === "number")
    return `${result.changes_found} text-fitting changes found · ${Number(result.overflow_skipped || 0)} protected overflows skipped.`;
  if (typeof result.reviewed_files === "number")
    return `${result.reviewed_files} current runtime files reviewed.`;
  if (typeof result.path === "string") return result.path;
  if (Array.isArray(result.messages))
    return result.messages
      .filter((value) => typeof value === "string")
      .join(" ");
  return "";
}

/** What a row adds beyond its title: a result summary or a message that is
    more than the title marked done. */
export function activityDetail(job: Job) {
  const summary = operationSummary(job);
  if (summary) return summary;
  const plain = (text: string) =>
    text
      .trim()
      .toLocaleLowerCase()
      .replace(/[.!\s]+$/, "")
      .replace(/^(completed|complete|finished|done):\s*/, "")
      .replace(/\s+(completed|complete|finished|done)$/, "");
  const message = job.message || "";
  return message && plain(message) !== plain(job.label || "") ? message : "";
}

export function projectActivity(
  operations: GuidedState["operations"],
  jobs: TranslationState["jobs"],
): Job[] {
  return [
    ...operations,
    ...jobs
      .filter((job) => job.kind === "operation")
      .map((job) => ({
        id: job.id,
        label: job.label,
        status: job.status,
        message: job.message,
        action: job.action || undefined,
        result: job.result,
        created: job.created,
        updated: job.updated,
        log: [],
      })),
  ].sort(
    (left, right) =>
      Date.parse(right.updated || right.created || "") -
      Date.parse(left.updated || left.created || ""),
  );
}

const outcomeIcons = {
  active: LoaderCircle,
  approval: Clock3,
  review: AlertTriangle,
  failed: XCircle,
  stopped: Pause,
  canceled: CircleSlash,
  estimate: FileCheck2,
  saved: Check,
  partial: Pause,
  missing: AlertTriangle,
  empty: CircleSlash,
  finished: CircleHelp,
};
const sentence = (value: string) =>
  value.charAt(0).toUpperCase() + value.slice(1);
function Outcome({ value }: { value: HistoryOutcome }) {
  const Icon = outcomeIcons[value.kind];
  return (
    <div className="history-outcome">
      <span className="history-status" data-kind={value.kind}>
        <Icon
          size={14}
          className={value.kind === "active" ? "job-status-spinner" : undefined}
          aria-hidden="true"
        />
        <strong>{value.label}</strong>
      </span>
      {value.detail && <small>{value.detail}</small>}
    </div>
  );
}

export function ActivityHistory({
  state,
  translation,
  inspect,
  initialQuery = "",
  footerTarget,
}: {
  state: GuidedState;
  translation: TranslationState;
  inspect: (job: Job) => void;
  /** Opens with this search, such as one stage's runs. */
  initialQuery?: string;
  /** The host footer that shows the record count. */
  footerTarget?: HTMLElement | null;
}) {
  const [visible, setVisible] = useState(30);
  const [tab, setTab] = useState("runs");
  const [query, setQuery] = useState(initialQuery);
  const [filter, setFilter] = useState("all");
  const runs = useMemo(
    () => state.runs.filter((job) => job.mode !== "estimate" && !job.temporary),
    [state.runs],
  );
  const estimates = useMemo(
    () => state.runs.filter((job) => job.mode === "estimate" && !job.temporary),
    [state.runs],
  );
  const operations = useMemo(
    () => projectActivity(state.operations, translation.jobs),
    [state.operations, translation.jobs],
  );
  const rows = useMemo(
    () =>
      (tab === "runs" ? runs : tab === "estimates" ? estimates : operations)
        .slice()
        .sort((a, b) => (b.created || "").localeCompare(a.created || "")),
    [tab, runs, estimates, operations],
  );
  const outcomes = useMemo(
    () => new Map(rows.map((job) => [job.id, historyOutcome(job)])),
    [rows],
  );
  const current = useMemo(
    () =>
      new Set(
        (
          ["database", "dialogue", "advanced", "variables", "speakers"] as const
        ).map((phase) => phaseRun(state.runs, phase)?.id),
      ),
    [state.runs],
  );
  const matching = rows.filter(
    (job) =>
      (filter === "all" ||
        (filter === "active" &&
          (job.mode === "batch" && job.process?.batches?.length
            ? batchInProgress(job)
            : activeRun(job))) ||
        (filter === "saved" && outcomes.get(job.id)?.kind === "saved") ||
        (filter === "failed" &&
          ["failed", "interrupted"].includes(job.status)) ||
        (filter === "canceled" &&
          ["canceled", "cancelled", "stopped"].includes(job.status))) &&
      [
        job.label,
        job.model,
        job.id,
        historyPhase(job),
        historyMode(job),
        ...(job.files || []),
      ]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()),
  );
  const groups: { day: string; date: string; jobs: Job[] }[] = [];
  for (const job of matching.slice(0, visible)) {
    const day = historyDay(job.created),
      last = groups.at(-1);
    if (last?.day === day) last.jobs.push(job);
    else groups.push({ day, date: historyDate(job.created), jobs: [job] });
  }
  const reset = () => {
    setFilter("all");
    setQuery("");
    setVisible(30);
  };
  return (
    <div className="guided-history">
      <Tabs
        id="activity-history"
        label="History type"
        items={[
          {
            id: "runs",
            label: (
              <>
                Translations{" "}
                {!!runs.length && (
                  <span className="history-tab-count">{runs.length}</span>
                )}
              </>
            ),
          },
          {
            id: "estimates",
            label: (
              <>
                Estimates{" "}
                {!!estimates.length && (
                  <span className="history-tab-count">{estimates.length}</span>
                )}
              </>
            ),
          },
          { id: "operations", label: "Other activity" },
        ]}
        value={tab}
        onChange={(value) => {
          setTab(value);
          setFilter("all");
          setVisible(30);
        }}
      />
      <div className="history-filters">
        <input
          type="search"
          aria-label="Search history"
          placeholder="Search files, model or task…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setVisible(30);
          }}
        />
        <select
          aria-label="History status"
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value);
            setVisible(30);
          }}
        >
          <option value="all">All statuses</option>
          <option value="active">In progress</option>
          {tab === "runs" && <option value="saved">Output saved</option>}
          <option value="failed">Failed / interrupted</option>
          <option value="canceled">Canceled / stopped</option>
        </select>
        <HelpPopover label="History">
          Each attempt keeps its date, model and outcome. Inspect an attempt to
          read its requests and manage Batch work.
        </HelpPopover>
      </div>
      <div
        key={`${tab}-${filter}-${query}`}
        className="history-list"
        role="tabpanel"
        id={`activity-history-panel-${tab}`}
        aria-labelledby={`activity-history-tab-${tab}`}
      >
        {!matching.length && (
          <div className="history-empty">
            <p className="muted">
              {rows.length
                ? "No records match these filters."
                : `No ${tab === "runs" ? "translation runs" : tab === "estimates" ? "estimates" : "other activity"} saved yet.`}
            </p>
            {rows.length > 0 && (
              <Button variant="quiet" onClick={reset}>
                Clear filters
              </Button>
            )}
          </div>
        )}
        {groups.map((group) => (
          <section
            className="history-day"
            key={group.day}
            aria-label={group.date}
          >
            <h3>{group.date}</h3>
            <ActionList compact>
              {group.jobs.map((job) => {
                const outcome = outcomes.get(job.id)!;
                return (
                  <ActionRow
                    key={job.id}
                    label={
                      <div
                        className={`history-entry${tab === "operations" ? " history-entry--operation" : ""}`}
                      >
                        <div className="history-identity">
                          <div>
                            <strong>
                              {tab === "operations"
                                ? job.label || "Saved activity"
                                : historyPhase(job)}
                            </strong>
                            {tab !== "operations" && (
                              <span className="history-method">
                                {historyMode(job)}
                              </span>
                            )}
                            {current.has(job.id) && (
                              <span className="history-latest">Latest</span>
                            )}
                          </div>
                          <small>
                            {job.created && (
                              <time
                                dateTime={job.created}
                                title={new Date(job.created).toLocaleString()}
                              >
                                {new Date(job.created).toLocaleTimeString([], {
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })}
                              </time>
                            )}
                            {job.model && <span>{job.model}</span>}
                          </small>
                        </div>
                        {tab === "operations" ? (
                          <div className="history-operation-detail">
                            <small>{activityDetail(job)}</small>
                          </div>
                        ) : (
                          <div className="history-scope">
                            <span>
                              {job.files
                                ? `${job.files.length} ${job.files.length === 1 ? "file" : "files"}`
                                : "Scope not recorded"}
                            </span>
                            <small>
                              {job.files?.slice(0, 2).join(", ")}
                              {job.files && job.files.length > 2
                                ? ` +${job.files.length - 2}`
                                : ""}
                            </small>
                          </div>
                        )}
                        {/* Finished activity needs no status; others say theirs. */}
                        {tab === "operations" ? (
                          job.status !== "complete" && (
                            <Outcome
                              value={{
                                kind: activeRun(job)
                                  ? "active"
                                  : job.status === "failed"
                                    ? "failed"
                                    : "stopped",
                                label: sentence(
                                  job.status.replaceAll("_", " "),
                                ),
                                detail: "",
                              }}
                            />
                          )
                        ) : (
                          <Outcome value={outcome} />
                        )}
                      </div>
                    }
                  >
                    <Button
                      variant="quiet"
                      aria-label={`Inspect ${tab === "operations" ? job.label || "activity" : historyPhase(job) + " " + historyMode(job)}${job.created ? " from " + new Date(job.created).toLocaleString() : ""}`}
                      onClick={() => inspect(job)}
                    >
                      Inspect
                      <ChevronRight size={14} aria-hidden="true" />
                    </Button>
                  </ActionRow>
                );
              })}
            </ActionList>
          </section>
        ))}
        {matching.length > visible && (
          <Button onClick={() => setVisible((count) => count + 30)}>
            Show older records ({matching.length - visible})
          </Button>
        )}
      </div>
      <ActionSlot target={footerTarget}>
        <div className="history-footer">
          <span>
            {!rows.length
              ? ""
              : matching.length === rows.length
                ? `${rows.length} ${rows.length === 1 ? "record" : "records"}`
                : `${matching.length} of ${rows.length} records`}
          </span>
          <span>
            {tab === "estimates"
              ? "Local plans · no translation submitted by an estimate"
              : "Newest first"}
          </span>
        </div>
      </ActionSlot>
    </div>
  );
}
