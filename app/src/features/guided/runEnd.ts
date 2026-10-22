/** How a run that ended without finishing reads beside its control. */
export type RunEnd = {
  /** Why it failed or was interrupted; empty for a run that finished or one the user stopped. */
  failure: string;
  /** What a stop the user asked for left, as a neutral note; empty for any other end. */
  stopped: string;
};

const none: RunEnd = { failure: "", stopped: "" };

/**
 * The one rule for a run's unfinished end: a stop the user asked for is not a
 * failure, so it reads as a note of what the stop left, never as an error,
 * while a run that failed or was cut off reads as the failure it is.
 */
export function runEnd(
  end: { status: string; message: string } | undefined,
  fallback: string,
): RunEnd {
  if (!end) return none;
  if (end.status === "stopped")
    return { failure: "", stopped: end.message || "It ended early." };
  return ["failed", "interrupted"].includes(end.status)
    ? { failure: end.message || fallback, stopped: "" }
    : none;
}

/** A stopped run as the job an action control reports beside its button. */
export const stoppedJob = (label: string, message: string) => ({
  label,
  status: "stopped",
  message,
});
