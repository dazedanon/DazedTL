import {
  useEffect,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
} from "react";
import { DraftSession } from "./DraftSession";
import { retainDraft } from "./leaveGuards";

type Options<T> = {
  persist: (value: T) => Promise<unknown>;
  report: (error: unknown) => void;
  fingerprint?: (value: T) => string;
  /** Writes save the value, so a successful write leaves the draft clean. */
  autosave?: boolean;
  initial?: { saved: T; draft?: T };
};

function createSession<T>({
  persist,
  report,
  fingerprint,
  autosave,
  initial,
}: Options<T>) {
  const session = new DraftSession<T>(persist, report, {
    fingerprint,
    autosave,
  });
  if (initial) session.adopt(initial.saved, initial.draft);
  return session;
}

/** Identity binds a session to its project/document for its entire lifetime. */
export function useDraft<T>(identity: string, options: Options<T>) {
  // State, not a memo: React may discard memoized values, which would drop drafts.
  const [owned, setOwned] = useState(() => ({
    identity,
    session: createSession(options),
  }));
  let session = owned.session;
  if (owned.identity !== identity) {
    session = createSession(options);
    setOwned({ identity, session });
  }
  const { persist, report, fingerprint } = options;
  useLayoutEffect(() => {
    session.configure(persist, report, fingerprint);
  }, [session, persist, report, fingerprint]);
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot);
  useEffect(() => {
    const release = retainDraft(session);
    return () => {
      void release().catch(session.fail);
    };
  }, [session]);
  return { ...state, session };
}
