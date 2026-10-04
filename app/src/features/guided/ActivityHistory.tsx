import type { Job, TranslationState, GuidedState } from "../../api/contracts";
import { Tabs } from "../../ui/Tabs";
import { activeRun, needsSubmissionReview, phaseRun } from "./translationView";
import { runLabel } from "./ProcessPanel";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { ActionControl } from "../../ui/ActionControl";
import { useState } from "react";
import { Button } from "../../ui/Button";

export function operationSummary(job: Job): string {
  const result = job.result;
  if (!result) return "";
  if (typeof result.archive === "string") return `${Number(result.files || 0)} ${result.files === 1 ? "source" : "sources"} refreshed. Previous copies and outputs archived.`;
  if (typeof result.files === "number") return `${result.files} ${result.files === 1 ? "file" : "files"} saved.`;
  if (typeof result.changes_found === "number") return `${result.changes_found} text-fitting changes found · ${Number(result.overflow_skipped || 0)} protected overflows skipped.`;
  if (typeof result.reviewed_files === "number") return `${result.reviewed_files} current runtime files reviewed.`;
  if (typeof result.path === "string") return result.path;
  if (Array.isArray(result.messages)) return result.messages.filter((value) => typeof value === "string").join(" ");
  return "";
}

export function projectActivity(state: GuidedState, translation: TranslationState): Job[] {
  return [...state.operations, ...translation.jobs.filter((job) => job.kind === "operation").map((job) => ({
    id: job.id, label: job.label, status: job.status, message: job.message, action: job.action || undefined,
    result: job.result, created: job.created, updated: job.updated, log: [],
  }))].sort((left, right) => Date.parse(right.updated || right.created || "") - Date.parse(left.updated || left.created || ""));
}

export function ActivityHistory({ state, translation, inspect, initialFilter = "all" }: {
  state: GuidedState; translation: TranslationState; inspect: (job: Job) => void; initialFilter?: string;
}) {
  const [visible, setVisible] = useState(12);
  const [tab, setTab] = useState("runs");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState(initialFilter);
  const rows = (tab === "runs" ? state.runs : projectActivity(state, translation)).slice().sort((a, b) =>
    (b.created || "").localeCompare(a.created || ""));
  const matches = rows.filter(job => (filter === "all" || filter === "attention" && (activeRun(job) || needsSubmissionReview(job))
    || filter === "dismissed" && job.keptForHistory || filter === "failed" && ["failed", "interrupted"].includes(job.status))
    && [job.label, job.model, job.id, job.logicalPhase, job.mode, ...(job.files || [])].join(" ").toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <div className="guided-history">
    <Tabs id="activity-history" label="History type" items={[{ id: "runs", label: "Translation runs" }, { id: "operations", label: "Other activity" }]}
      value={tab} onChange={value => { setTab(value); setVisible(12); setFilter("all"); }} />
    <div className="history-filters"><input type="search" aria-label="Search history" placeholder="Find a file, model or run…" value={query} onChange={event => { setQuery(event.target.value); setVisible(12); }} />
      <select aria-label="History status" value={filter} onChange={event => { setFilter(event.target.value); setVisible(12); }}><option value="all">All saved activity</option><option value="attention">Active / unresolved</option><option value="failed">Failed / interrupted</option><option value="dismissed">Dismissed</option></select>
      <small>{matches.length} {tab === "runs" ? matches.length === 1 ? "run" : "runs" : matches.length === 1 ? "activity" : "activities"}</small></div>
    <div className="history-list" role="tabpanel" id={`activity-history-panel-${tab}`} aria-labelledby={`activity-history-tab-${tab}`}>
      {!matches.length && <p className="muted">{rows.length ? "No saved activity matches these filters." : "No saved activity for this project yet."}</p>}
      <ActionList compact>{matches.slice(0, visible).map(job => {
        const current = job.logicalPhase && phaseRun(state.runs, job.logicalPhase)?.id === job.id;
        return <ActionRow key={job.id} label={<div className="history-entry">
          <div><strong>{tab === "runs" ? runLabel(job) : job.label || "Saved activity"}</strong><span className="badge">{job.status}</span>
            {activeRun(job) ? <span>Active</span> : needsSubmissionReview(job) ? <span className="translation-error">Submission review needed</span> : current ? <span className="muted">Latest attempt</span> : null}{job.keptForHistory && <span className="muted">Dismissed</span>}</div>
          <small>{job.created ? <time dateTime={job.created}>{new Date(job.created).toLocaleString()}</time> : "Date not recorded"}{job.model && ` · ${job.model}`}{job.files && ` · ${job.files.length} files`}</small>
          {job.files && <small>{job.files.slice(0, 3).join(", ")}{job.files.length > 3 ? ` + ${job.files.length - 3} more` : ""}</small>}
          {job.process && <small>{job.process.prepared ?? "—"} prepared · {job.process.received ?? "—"} received{job.process.failed ? ` · ${job.process.failed} rejected` : ""}</small>}
          {tab === "operations" && (operationSummary(job) || job.message) && <small>{operationSummary(job) || job.message}</small>}
        </div>}><ActionControl label={tab === "runs" ? "Inspect run" : "View details"} variant="quiet" onClick={() => inspect(job)} /></ActionRow>;
      })}</ActionList>
      {matches.length > visible && <Button onClick={() => setVisible(count => count + 12)}>Show older activity</Button>}
    </div>
  </div>;
}
