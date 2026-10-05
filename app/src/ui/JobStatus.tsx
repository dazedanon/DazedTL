import { Check, LoaderCircle } from "lucide-react";
import type { TranslationJob } from "../api/contracts";

export function JobStatus({
  job,
  compact = false,
}: {
  job: Pick<TranslationJob, "label" | "status" | "message">;
  compact?: boolean;
}) {
  const active = job.status === "running" || job.status === "waiting";
  // Older saved operations also carry generic completion wording. Keep any
  // useful detail following it without repeating the heading and state.
  const message = job.message.trim();
  const completion =
    job.status === "complete"
      ? [`${job.label} completed.`, `Completed: ${job.label}`].find(
          (prefix) =>
            message === prefix ||
            (message.startsWith(prefix) &&
              /^\s/.test(message.slice(prefix.length))),
        )
      : undefined;
  const detail = completion ? message.slice(completion.length).trim() : message;

  return (
    <div className="job-status-status" role="status" aria-atomic="true">
      <div className="job-status-heading">
        {!compact && <strong>{job.label}</strong>}
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
          {compact && !active && "Last run: "}
          {job.status.replaceAll("_", " ")}
        </span>
      </div>
      {detail && <p>{detail}</p>}
    </div>
  );
}
