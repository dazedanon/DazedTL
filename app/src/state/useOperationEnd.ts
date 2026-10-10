import { useEffect, useRef } from "react";

type Observed = { id: string; status: string; message?: string | null };

const unfinished = ["ready", "running", "waiting"];

/**
 * Waits, through the page's observed jobs, for an operation started here to
 * end, and says how it ended; nothing is polled for it. A job reports its
 * end before its worker exits, and the backend starts the next step only
 * once no worker runs.
 */
export function useOperationEnd(jobs: readonly Observed[], running: boolean) {
  const latest = useRef({ jobs, running });
  const waiters = useRef(new Set<() => void>());
  useEffect(() => {
    latest.current = { jobs, running };
    for (const check of waiters.current) check();
  });
  return (id: string) =>
    new Promise<{ status: string; message: string }>((resolve) => {
      const check = () => {
        const job = latest.current.jobs.find((item) => item.id === id);
        if (!job || unfinished.includes(job.status) || latest.current.running)
          return;
        waiters.current.delete(check);
        resolve({ status: job.status, message: job.message || "" });
      };
      waiters.current.add(check);
      check();
    });
}
