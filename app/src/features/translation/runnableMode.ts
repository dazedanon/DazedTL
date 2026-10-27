/**
 * The method a chosen mode shows and runs as in both workflows: Batch on a
 * connection that cannot run it, which the backend explains in `unavailable`,
 * is Live, named `live` by the workflow. Saved options and drafts keep the
 * choice, so a connection that runs Batch brings it back; the backend runs
 * saved options by the same rule (runnable_mode in
 * backend/dazedtl/settings/execution.py).
 */
export const runnableMode = <M extends string>(
  mode: M,
  unavailable: string,
  live: M,
): M => (mode === "batch" && unavailable ? live : mode);
