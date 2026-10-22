import {
  createContext,
  useContext,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { DisplayState } from "./displayStatus";
import { FeedbackStore } from "./feedbackStore";

const Owners = createContext<FeedbackStore | null>(null);

/**
 * Lets a fallback message skip errors that their control already reports,
 * and a control skip a success its status heading already says. A scope
 * inside another shares it, so a component can bring its own scope and
 * still report to its host's.
 */
export function FeedbackOwners({ children }: { children: ReactNode }) {
  const parent = useContext(Owners);
  const [store] = useState(() => parent ?? new FeedbackStore());
  return <Owners.Provider value={store}>{children}</Owners.Provider>;
}

/** Marks key as reported inline while the calling control is mounted. */
export function useFeedbackOwner(key: string | undefined) {
  const store = useContext(Owners);
  useLayoutEffect(
    () => (store && key ? store.register(key) : undefined),
    [store, key],
  );
}

/** Whether a mounted control inside the nearest scope reports key itself. */
export function useOwnedFeedback(key: string) {
  const store = useContext(Owners);
  return useSyncExternalStore(
    store?.subscribe || noSubscription,
    () => !!store?.has(key),
  );
}

const noSubscription = () => () => {};

/** Records that the calling heading shows key's outcome as state while mounted. */
export function useOutcomeHeading(
  key: string | undefined,
  state: DisplayState | undefined,
) {
  const store = useContext(Owners);
  useLayoutEffect(
    () => (store && key && state ? store.report(key, state) : undefined),
    [store, key, state],
  );
}

/** Whether a mounted heading inside the nearest scope says key's work is done. */
export function useOutcomeShown(key: string | undefined) {
  const store = useContext(Owners);
  return useSyncExternalStore(
    store?.subscribe || noSubscription,
    () => !!store && !!key && store.saysDone(key),
  );
}
