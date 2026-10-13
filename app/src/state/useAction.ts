import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { messageOf } from "../api/errors";

type Result<T> = { ok: true; value: T } | { ok: false };
/** The observed state an action's writes change, such as the application. */
export interface Observer {
  mark: () => number;
  /** Waits for an observation of any write begun after `mark()` gave `since`. */
  settle: (since: number) => Promise<unknown>;
}
/**
 * Local action feedback and a synchronous guard against duplicate submissions.
 * An action finishes once its `observer` shows what it wrote, then runs `after`.
 */
export function useAction({
  observer,
  after,
}: { observer?: Observer; after?: () => void | Promise<unknown> } = {}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [key, setKey] = useState("");
  const pending = useRef(false);
  const mounted = useRef(true);
  const observerRef = useRef(observer);
  const afterRef = useRef(after);
  useLayoutEffect(() => {
    observerRef.current = observer;
    afterRef.current = after;
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const report = useCallback((value: unknown, actionKey = "") => {
    if (mounted.current) {
      setKey(actionKey);
      setError(messageOf(value));
      setNotice("");
    }
  }, []);
  const clear = useCallback(() => {
    setKey("");
    setError("");
    setNotice("");
  }, []);
  const succeed = useCallback((message: string, actionKey = "") => {
    setKey(actionKey);
    setError("");
    setNotice(message);
  }, []);
  const run = useCallback(
    async <T>(
      task: () => Promise<T>,
      message = "",
      actionKey = "",
    ): Promise<Result<T>> => {
      if (pending.current) return { ok: false };
      pending.current = true;
      setKey(actionKey);
      setBusy(true);
      setError("");
      setNotice("");
      const since = observerRef.current?.mark();
      try {
        const value = await task();
        if (since !== undefined) await observerRef.current?.settle(since);
        await afterRef.current?.();
        if (mounted.current) setNotice(message);
        return { ok: true, value };
      } catch (error) {
        report(error, actionKey);
        return { ok: false };
      } finally {
        pending.current = false;
        if (mounted.current) setBusy(false);
      }
    },
    [report],
  );
  return { busy, error, notice, key, run, report, clear, succeed };
}
