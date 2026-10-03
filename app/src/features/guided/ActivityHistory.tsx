import type { Job, TranslationState, GuidedState } from "../../api/contracts";
import { JobStatus } from "../../ui/JobStatus";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { ActionControl } from "../../ui/ActionControl";

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

export function ActivityHistory({ state, translation, inspect }: {
  state: GuidedState; translation: TranslationState; inspect: (job: Job) => void;
}) {
  const rows = [...projectActivity(state, translation), ...state.runs].sort((a, b) =>
    Date.parse(b.updated || b.created || "") - Date.parse(a.updated || a.created || ""));
  const kept = rows.filter(job => job.keptForHistory);
  const list = (jobs: Job[]) => <ActionList>{jobs.map((job) => <ActionRow key={job.id} label={<div>
      <JobStatus job={{ ...job, label: job.label || (job.mode === "estimate" ? "Cost estimate" : "Translation run") }} />
      {job.updated && <time className="muted" dateTime={job.updated}>{new Date(job.updated).toLocaleString()}</time>}
      {job.files && <p className="muted">{job.files.length} {job.files.length === 1 ? "file" : "files"} · {job.model || "Saved model"} · {job.mode}</p>}
      {operationSummary(job) && <p className="path">{operationSummary(job)}</p>}
    </div>}><ActionControl label="View details" variant="quiet" onClick={() => inspect(job)} /></ActionRow>)}</ActionList>;
  return <div className="guided-history">
    {!rows.length && <p className="muted">No saved activity for this project yet.</p>}
    {!!kept.length && <section aria-label="Kept failed runs"><h3>Kept failed runs</h3>{list(kept)}</section>}
    {list(rows.filter(job => !job.keptForHistory).slice(0, 12))}
  </div>;
}
