import {
  useCallback,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

export interface Shown<T, V extends T | null = T> {
  value: V | T;
  /** The newest snapshot the value accounts for. */
  seen: T | null | undefined;
  /** The newest snapshot merged into a held value. */
  merged: T | null | undefined;
  /** Set when a snapshot replaced the value. */
  adopted?: { next: T; previous: V | T };
}

/** A loaded value or reply accounts for the snapshots observed before it. */
export const replied = <T, V extends T | null = T>(
  value: V | T,
  observed: T | null | undefined,
): Shown<T, V> => ({ value, seen: observed, merged: observed });

/** What a view shows once `observed` arrives; unchanged when nothing applies. */
export function reconcile<T, V extends T | null = T>(
  shown: Shown<T, V>,
  observed: T | null | undefined,
  hold: boolean,
  merge?: (current: T, observed: T) => T,
): Shown<T, V> {
  if (!observed || observed === shown.seen) return shown;
  if (!hold)
    return {
      value: observed,
      seen: observed,
      merged: observed,
      adopted: { next: observed, previous: shown.value },
    };
  if (merge && shown.value && observed !== shown.merged)
    return {
      ...shown,
      value: merge(shown.value, observed),
      merged: observed,
    };
  return shown;
}

/**
 * Backend state a view observes and also replaces with its own replies.
 * Replies show at once and account for every snapshot observed so far. A newer
 * snapshot replaces the value during render unless `hold` defers it while
 * unsaved edits or actions still build on the current revision; `merge` copies
 * the fields a held view may still refresh. `onAdopt` updates external stores,
 * such as a draft session, before an adopted snapshot paints.
 */
export function useObserved<T, V extends T | null = T | null>(
  observed: T | null | undefined,
  initial: V,
  {
    hold,
    merge,
    onAdopt,
  }: {
    hold: boolean;
    merge?: (current: T, observed: T) => T;
    onAdopt?: (next: T, previous: V | T) => void;
  },
) {
  const [shown, setShown] = useState(() => replied<T, V>(initial, observed));
  const current = reconcile(shown, observed, hold, merge);
  if (current !== shown) setShown(current);
  const latest = useRef(current.value);
  const lastObserved = useRef(observed);
  useLayoutEffect(() => {
    latest.current = shown.value;
  }, [shown]);
  useLayoutEffect(() => {
    lastObserved.current = observed;
  }, [observed]);
  const adopted = useEffectEvent((next: T, previous: V | T) =>
    onAdopt?.(next, previous),
  );
  useLayoutEffect(() => {
    if (shown.adopted) adopted(shown.adopted.next, shown.adopted.previous);
  }, [shown.adopted]);
  const set = useCallback((value: T) => {
    latest.current = value;
    setShown(replied<T, V>(value, lastObserved.current));
  }, []);
  const read = useCallback(() => latest.current, []);
  return { value: current.value, set, latest: read };
}
