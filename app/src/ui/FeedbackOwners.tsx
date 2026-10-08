import {
  createContext,
  useContext,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

/** Action keys whose result a mounted control already shows beside itself. */
class OwnerStore {
  private owners = new Map<string, number>();
  private listeners = new Set<() => void>();

  register(key: string) {
    this.owners.set(key, (this.owners.get(key) || 0) + 1);
    this.notify();
    return () => {
      const count = (this.owners.get(key) || 1) - 1;
      if (count) this.owners.set(key, count);
      else this.owners.delete(key);
      this.notify();
    };
  }

  has = (key: string) => this.owners.has(key);

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private notify() {
    for (const listener of this.listeners) listener();
  }
}

const Owners = createContext<OwnerStore | null>(null);

/**
 * Lets a fallback message skip errors that their control already reports. A
 * scope inside another shares it, so a component can bring its own scope
 * and still report to its host's.
 */
export function FeedbackOwners({ children }: { children: ReactNode }) {
  const parent = useContext(Owners);
  const [store] = useState(() => parent ?? new OwnerStore());
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
