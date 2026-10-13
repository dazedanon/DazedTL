import { useEffect, useState } from "react";
import {
  addSample,
  remainingSeconds,
  type ProgressSample,
} from "../ui/workTime";
import { useOnChange } from "./useOnChange";

/** The current time, each second while `active`, for time spent and left. */
export function useSecond(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const tick = () => setNow(Date.now());
    // The first tick refreshes a time held since the work last stopped.
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, 1000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [active]);
  return now;
}

type Clock = {
  session: string;
  step?: string;
  last?: string;
  since: number;
  spent: Record<string, number>;
};

/**
 * Milliseconds each step of one piece of work, which `session` names, has
 * spent working, and the step that worked last. Only the `step` given now
 * accrues time, so a pause such as a review in between, given as no step,
 * is not counted.
 */
export function useStepClock(
  session: string,
  step: string | undefined,
  now: number,
) {
  const [clock, setClock] = useState<Clock>(() => ({
    session,
    step,
    last: step,
    since: Date.now(),
    spent: {},
  }));
  useOnChange(`${session}\u0000${step ?? ""}`, () => {
    const at = Date.now();
    const same = clock.session === session;
    const spent = same ? { ...clock.spent } : {};
    if (same && clock.step)
      spent[clock.step] = (spent[clock.step] ?? 0) + at - clock.since;
    setClock({
      session,
      step,
      last: step ?? (same ? clock.last : undefined),
      since: at,
      spent,
    });
  });
  return {
    spent: (id: string) =>
      (clock.spent[id] ?? 0) +
      (clock.step === id ? Math.max(0, now - clock.since) : 0),
    last: clock.last,
  };
}

/**
 * Seconds a counted step still needs at its recent pace, from the readings
 * seen since `key` (the step and the work counting it) began. Another key
 * starts over, so one step's pace never times the next.
 */
export function useRemaining(
  key: string,
  progress: { current: number; total: number } | undefined,
  now: number,
) {
  const current = progress?.current;
  const [samples, setSamples] = useState<ProgressSample[]>([]);
  useOnChange(`${key}\u0000${current ?? ""}`, (_value, previous) => {
    if (current === undefined) return setSamples([]);
    const sample = { at: Date.now(), current };
    setSamples(
      previous.startsWith(`${key}\u0000`)
        ? addSample(samples, sample)
        : [sample],
    );
  });
  return progress ? remainingSeconds(samples, progress.total, now) : undefined;
}
