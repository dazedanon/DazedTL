import { useEffect, useEffectEvent, useState } from "react";

type Settled<T> = { request: string; value?: T; error?: unknown };

/**
 * Reads data for `key`, or nothing while `key` is null. A newer key or unmount
 * aborts the previous read and drops its result, and pending state follows the
 * key instead of being reset inside an effect.
 */
export function useRead<T>(
  key: string | null,
  read: (signal: AbortSignal) => Promise<T>,
) {
  const [attempt, setAttempt] = useState(0);
  const request = key === null ? null : `${attempt}:${key}`;
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const load = useEffectEvent(read);
  useEffect(() => {
    if (request === null) return;
    const controller = new AbortController();
    load(controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setSettled({ request, value });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setSettled({ request, error });
      },
    );
    return () => controller.abort();
  }, [request]);
  const result = settled?.request === request ? settled : null;
  return {
    value: result?.value,
    error: result?.error,
    pending: request !== null && !result,
    retry: () => setAttempt((value) => value + 1),
  };
}
