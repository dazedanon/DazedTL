import {
  useEffect,
  useId,
  useRef,
  type ComponentProps,
  type ReactNode,
} from "react";
import { Button } from "./Button";
import { Feedback } from "./Feedback";
import { JobStatus } from "./JobStatus";
import type { Job } from "../api/contracts";
import { useFeedbackOwner } from "./FeedbackOwners";

// Successes finished before this interface loaded belong to History, not
// beside the control; failures stay until a newer attempt replaces them.
const loadedAt = performance.timeOrigin;
const earlierSuccess = (job: Pick<Job, "status" | "updated">) =>
  job.status === "complete" &&
  !!job.updated &&
  Date.parse(job.updated) < loadedAt;

export function ActionControl({
  label,
  pending = false,
  pendingText = "Working…",
  error = "",
  notice = "",
  inline = false,
  feedbackKey,
  disabledReason = "",
  job: reported,
  icon,
  ...button
}: Omit<ComponentProps<typeof Button>, "children"> & {
  label: string;
  /** An icon before the label, for actions the icon rule marks (open a folder, add). */
  icon?: ReactNode;
  /** The action key whose result this control reports, so fallbacks skip it. */
  feedbackKey?: string;
  pendingText?: string;
  error?: string;
  notice?: string;
  inline?: boolean;
  /** Shown beside the control while it is disabled for this reason. */
  disabledReason?: string;
  job?: Pick<Job, "label" | "status" | "message" | "updated">;
}) {
  const job = reported && !earlierSuccess(reported) ? reported : undefined;
  const active = job && ["ready", "running", "waiting"].includes(job.status);
  useFeedbackOwner(feedbackKey);
  const feedbackId = useId();
  const control = useRef<HTMLDivElement>(null);
  const feedback = useRef<HTMLDivElement>(null);
  const invoked = useRef(false);
  const failure =
    error ||
    (job && ["failed", "interrupted"].includes(job.status)
      ? job.message || job.status
      : "");
  useEffect(() => {
    if (failure && !pending && !active && invoked.current) {
      invoked.current = false;
      if (
        document.activeElement === document.body ||
        control.current?.contains(document.activeElement)
      ) {
        feedback.current?.scrollIntoView({
          block: "nearest",
          inline: "nearest",
        });
      }
    }
  }, [failure, pending, active]);
  const result =
    pending || (inline && active) ? (
      !inline && <Feedback loading loadingText={pendingText} />
    ) : error ? (
      <Feedback error={error} />
    ) : job ? (
      <JobStatus
        compact
        job={{
          label: job.label || label,
          status: job.status,
          message: job.message,
        }}
      />
    ) : notice ? (
      <Feedback notice={notice} />
    ) : button.disabled && disabledReason ? (
      <span className="action-control-reason">{disabledReason}</span>
    ) : null;
  return (
    <div
      className={`action-control${inline ? " action-control--inline" : ""}`}
      ref={control}
    >
      <Button
        {...button}
        pending={pending || !!active}
        onClick={(event) => {
          invoked.current = true;
          button.onClick?.(event);
        }}
        aria-describedby={[button["aria-describedby"], feedbackId]
          .filter(Boolean)
          .join(" ")}
      >
        {!(pending || active) && icon}
        <span className="action-control-label">
          {inline && (pending || active) ? pendingText : label}
        </span>
      </Button>
      <div id={feedbackId} className="action-control-feedback" ref={feedback}>
        {result}
      </div>
    </div>
  );
}
