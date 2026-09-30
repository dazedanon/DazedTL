import { useCallback, useEffect, useRef, useState } from "react";
import { messageOf } from "../api/errors";

type Result<T> = { ok: true; value: T } | { ok: false };
/** Local action feedback and a synchronous guard against duplicate submissions. */
export function useAction({
  after,
}: { after?: () => void | Promise<unknown> } = {}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  const mounted = useRef(true);
  const afterRef = useRef(after);
  afterRef.current = after;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const report = useCallback((value: unknown) => {
    if (mounted.current) {
      setError(messageOf(value));
      setNotice("");
    }
  }, []);
  const clear = useCallback(() => {
    setError("");
    setNotice("");
  }, []);
  const succeed = useCallback((message: string) => {
    setError("");
    setNotice(message);
  }, []);
  const run = useCallback(
    async <T>(task: () => Promise<T>, message = ""): Promise<Result<T>> => {
      if (pending.current) return { ok: false };
      pending.current = true;
      setBusy(true);
      setError("");
      setNotice("");
      try {
        const value = await task();
        await afterRef.current?.();
        if (mounted.current) setNotice(message);
        return { ok: true, value };
      } catch (error) {
        report(error);
        return { ok: false };
      } finally {
        pending.current = false;
        if (mounted.current) setBusy(false);
      }
    },
    [report],
  );
  return { busy, error, notice, run, report, clear, succeed };
}
