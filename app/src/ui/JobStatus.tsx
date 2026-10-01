import { Check, LoaderCircle } from "lucide-react";
import type { TranslationJob } from "../api/contracts";

export function JobStatus({
  job,
}: {
  job: Pick<TranslationJob, "label" | "status" | "message">;
}) {
  const active = job.status === "running" || job.status === "waiting";
  // Older saved operations also carry this generic completion message.
  const redundant =
    job.status === "complete" &&
    job.message.trim() === `${job.label} completed.`;

  return (
    <div className="job-status-status" role="status" aria-atomic="true">
      <div className="job-status-heading">
        <strong>{job.label}</strong>
        <span className="job-status-state" data-state={job.status}>
          {active ? (
            <LoaderCircle
              size={15}
              className="job-status-spinner"
              aria-hidden="true"
            />
          ) : job.status === "complete" ? (
            <Check size={15} aria-hidden="true" />
          ) : null}
          {job.status.replaceAll("_", " ")}
        </span>
      </div>
      {job.message && !redundant && <p>{job.message}</p>}
    </div>
  );
}
