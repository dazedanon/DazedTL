import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { DraftSession } from "./DraftSession";
import { registerLeaveGuard } from "./leaveGuards";

/** Identity binds a session to its project/document for its entire lifetime. */
export function useDraft<T>(
  identity: string,
  options: {
    persist: (value: T) => Promise<unknown>;
    report: (error: unknown) => void;
    fingerprint?: (value: T) => string;
    initial?: { saved: T; draft?: T };
  },
) {
  const report = useRef(options.report);
  report.current = options.report;
  const session = useMemo(() => {
    const value = new DraftSession(
      options.persist,
      (error) => report.current(error),
      options.fingerprint,
    );
    if (options.initial)
      value.adopt(options.initial.saved, options.initial.draft);
    return value;
  }, [identity]);
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot);
  useEffect(() => {
    const unregister = registerLeaveGuard(session.flush);
    return () => {
      session
        .dispose()
        .catch((error) => report.current(error))
        .finally(unregister);
    };
  }, [session]);
  return { ...state, session };
}
