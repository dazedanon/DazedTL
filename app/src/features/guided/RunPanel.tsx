import { Button } from "../../ui/Button";
import type { Job } from "../../api/contracts";
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
        .filter(([key]) => typeof value[key] === "number")
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
  exportFiles,
  apply,
  busy,
}: {
  job: Job;
  active: boolean;
  stop: () => void;
  resume: () => void;
  answer: (approved: boolean) => void;
  exportFiles: () => void;
  apply: () => void;
  busy: boolean;
}) {
  return (
    <section className="card run-panel">
      <div className="section-heading">
        <h2>{job.mode === "estimate" ? "Cost estimate" : "Translation run"}</h2>
        <span className="badge">{job.status}</span>
      </div>
      <p>{job.message}</p>
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
      {job.estimate && <Estimate value={job.estimate} />}
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
              onClick={() => answer(true)}
            >
              {job.approval.kind === "batch"
                ? "Submit batch"
                : "Translate speakers"}
            </Button>
            <Button
              size="comfortable"
              disabled={busy}
              onClick={() => answer(false)}
            >
              Decline
            </Button>
          </div>
        </div>
      )}
      <div className="actions">
        {active ? (
          <Button size="comfortable" disabled={busy} onClick={stop}>
            Stop run
          </Button>
        ) : ["failed", "stopped", "interrupted", "canceled"].includes(
            job.status,
          ) ? (
          <Button size="comfortable" disabled={busy} onClick={resume}>
            Resume saved run
          </Button>
        ) : null}
        {job.status === "complete" &&
          Object.keys(job.outputs || {}).length > 0 && (
            <>
              <Button size="comfortable" onClick={exportFiles} disabled={busy}>
                Save output copy
              </Button>
              <Button
                size="comfortable"
                variant="primary"
                onClick={apply}
                disabled={busy}
              >
                Apply translated files to game
              </Button>
            </>
          )}
      </div>
      {!!job.log?.length && (
        <details>
          <summary>Run log</summary>
          <pre>{job.log.join("\n")}</pre>
        </details>
      )}
    </section>
  );
}
