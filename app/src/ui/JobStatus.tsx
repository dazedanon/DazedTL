import { Check, LoaderCircle } from "lucide-react";
import type { TranslationJob } from "../api/contracts";
import { ExpandableText } from "./ExpandableText";

import { sentence } from "./displayText";

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
  const state = job.status.replaceAll("_", " ");

  return (
    <div
      className={`job-status-status${compact ? " job-status-status--compact" : ""}`}
      role="status"
      aria-atomic="true"
    >
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
          {compact && !active ? `Last run: ${state}` : sentence(state)}
        </span>
      </div>
      {detail && (
        <p>
          {compact ? (
            // Beside a control, a long detail stays an excerpt like an
            // action's error.
            <ExpandableText
              key={detail}
              text={detail}
              label={`${job.label} details`}
              appearance="inline"
              limit={120}
            />
          ) : (
            detail
          )}
        </p>
      )}
    </div>
  );
}
