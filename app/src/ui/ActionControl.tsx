import { useEffect, useId, useRef, type ComponentProps } from "react";
import { AlertCircle, Check } from "lucide-react";
import { Button } from "./Button";
import { Feedback } from "./Feedback";
import { JobStatus } from "./JobStatus";
import type { Job } from "../api/contracts";

export function ActionControl({
  label, pending = false, pendingText = "Working…", error = "", notice = "", job, ...button
}: Omit<ComponentProps<typeof Button>, "children"> & {
  label: string;
  pendingText?: string;
  error?: string;
  notice?: string;
  job?: Pick<Job, "label" | "status" | "message">;
}) {
  const active = job && ["ready", "running", "waiting"].includes(job.status);
  const feedbackId = useId();
  const control = useRef<HTMLDivElement>(null);
  const feedback = useRef<HTMLDivElement>(null);
  const invoked = useRef(false);
  const failure = error || (job && ["failed", "needs_attention", "interrupted"].includes(job.status) ? job.message || job.status : "");
  useEffect(() => {
    if (failure && !pending && !active && invoked.current) {
      invoked.current = false;
      if (document.activeElement === document.body || control.current?.contains(document.activeElement)) {
        feedback.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
    }
  }, [failure, pending, active]);
  const failed = !!error || !!job && ["failed", "needs_attention", "interrupted"].includes(job.status);
  const succeeded = !failed && (job?.status === "complete" || !!notice);
  return <div className="action-control" ref={control}>
    <Button {...button} pending={pending || !!active}
      onClick={(event) => { invoked.current = true; button.onClick?.(event); }}
      aria-describedby={[button["aria-describedby"], feedbackId].filter(Boolean).join(" ")}>
      {!pending && !active && (failed
        ? <AlertCircle size={14} className="action-result-icon action-result-icon--error" aria-hidden="true" />
        : succeeded ? <Check size={14} className="action-result-icon action-result-icon--success" aria-hidden="true" /> : null)}
      <span className="action-control-label">{label}</span>
    </Button>
    <div id={feedbackId} className="action-control-feedback" ref={feedback}>
      {pending ? <Feedback loading loadingText={pendingText} />
        : error ? <Feedback error={error} />
        : job ? <JobStatus compact job={{ label: job.label || label, status: job.status, message: job.message }} />
        : notice ? <Feedback notice={notice} /> : null}
    </div>
  </div>;
}
