import { Button } from "../../ui/Button";
import type { Job } from "../../api/contracts";
import { Message } from "../../ui/Feedback";
import { api } from "../../api/client";
import { ProcessPanel } from "./ProcessPanel";
import { canResumeRun } from "./translationView";
export function Estimate({ value }: { value: Record<string, unknown> }) {
  const fields = [
    ["requests", "Requests"],
    ["request_count", "Requests"],
    ["input_tokens", "Input tokens"],
    ["output_tokens", "Estimated output tokens"],
    ["live_cost", "Live estimate"],
    ["batch_cost", "Batch estimate"],
    ["batch_cached_cost", "Batch with cache"],
    ["batch_nocache_cost", "Batch without cache"],
  ];
  return (
    <dl className="estimate">
      {fields
        .filter(([key]) => typeof value[key] === "number" &&
          !(key === "request_count" && typeof value.requests === "number") &&
          !(key === "batch_cost" && typeof value.batch_cached_cost === "number" && value.batch_cost === value.batch_cached_cost))
        .map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {key.includes("cost")
                ? "$" + Number(value[key]).toFixed(5)
                : Number(value[key]).toLocaleString()}
            </dd>
          </div>
        ))}
    </dl>
  );
}

export default function RunPanel({
  job,
  active,
  stop,
  resume,
  answer,
  apply,
  busy,
  error = "",
  pendingKey = "",
  hideTitle = false,
  projectId,
}: {
  job: Job;
  active: boolean;
  stop: () => void;
  resume: () => void;
  answer: (approved: boolean) => void;
  apply?: () => void;
  busy: boolean;
  error?: string;
  pendingKey?: string;
  hideTitle?: boolean;
  projectId?: string;
}) {
  return (
    <section className="ui-section run-panel">
      <div className="section-heading">
        {!hideTitle && <h2>{job.mode === "estimate" ? "Cost estimate" : "Translation run"}</h2>}
        <span className="badge">{job.status}</span>
      </div>
      <p>{job.message}</p>
      <ProcessPanel job={job} readPayload={projectId ? index => api.guided.payload(projectId, job.id, index) : undefined}
        readNames={projectId ? offset => api.guided.nameResults(projectId, job.id, offset) : undefined} />
      {job.files && <details><summary>Frozen file scope</summary><ul>{job.files.map((name) => <li key={name}>{name}</li>)}</ul></details>}
      {job.eventTextReview && <details><summary>Saved event text review</summary>
        <p>{job.eventTextReview.literalBased ? "Reviewed literal-based comparison coverage." : job.eventTextReview.manual?.length ? "Manual overrides: " + job.eventTextReview.manual.join(", ") + ". Reason: " + job.eventTextReview.reason : "Reviewed investigation recommendations."}</p>
        {job.eventTextReview.settings && <dl>{Object.entries(job.eventTextReview.settings).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{Array.isArray(value) ? value.join(", ") || "None" : String(value)}</dd></div>)}</dl>}
      </details>}
      {active && job.mode === "batch" && <p className="muted">Submitted Batches are monitored automatically. Open Run history to inspect progress.</p>}
      {job.progress && (
        <>
          <progress
            max={job.progress.total || 1}
            value={job.progress.current}
          />
          <p className="muted">
            {job.progress.current} / {job.progress.total} files ·{" "}
            {job.progress.file}
          </p>
        </>
      )}
      {job.estimate && <details><summary>Cost estimate</summary><Estimate value={job.estimate} /></details>}
      {job.approval && (
        <div className="approval">
          <h3>
            {job.approval.kind === "batch"
              ? "Review batch submission"
              : "Translate speaker names?"}
          </h3>
          <Estimate value={job.approval.detail} />
          {Array.isArray(job.approval.detail.speakers) && (
            <p>
              {job.approval.detail.speakers
                .slice(0, 40)
                .map((v) => String(v))
                .join(", ")}
            </p>
          )}
          <p>
            Approving this request uses the provider and settings saved with
            this run. API charges apply.
          </p>
          <div className="actions">
            <Button
              size="comfortable"
              variant="primary"
              disabled={busy}
              pending={pendingKey === "run:answer:true"}
              onClick={() => answer(true)}
            >
              {job.approval.kind === "batch"
                ? "Submit batch"
                : "Translate speakers"}
            </Button>
            <Button
              size="comfortable"
              disabled={busy}
              pending={pendingKey === "run:answer:false"}
              onClick={() => answer(false)}
            >
              Decline
            </Button>
          </div>
        </div>
      )}
      <div className="actions">
        {active && job.mode !== "batch" ? (
          <Button size="comfortable" disabled={busy} pending={pendingKey === "run:stop"} onClick={stop}>
            Stop after current work
          </Button>
        ) : canResumeRun(job) ? (
          <Button size="comfortable" disabled={busy || job.process?.retryBlocked && !(job.mode === "batch" && job.phase?.startsWith("poll"))} onClick={resume}>
            Resume with saved settings
          </Button>
        ) : null}
        {job.status === "complete" && Object.keys(job.outputs || {}).length > 0 && apply && (
              <Button
                size="comfortable"
                variant="primary"
                onClick={apply}
                disabled={busy}
              >
                Review & apply outputs
              </Button>
          )}
      </div>
      <Message message={error} />
      {!!job.log?.length && (
        <details>
          <summary>Run log</summary>
          <pre>{job.log.join("\n")}</pre>
        </details>
      )}
    </section>
  );
}
