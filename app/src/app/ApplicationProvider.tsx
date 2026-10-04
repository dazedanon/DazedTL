import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import { onMutation } from "../api/transport";
import { ApplicationStore } from "./applicationStore";
import { flushDrafts } from "../state/leaveGuards";

const Context = createContext<ApplicationStore | null>(null);
export function ApplicationProvider({ children }: { children: ReactNode }) {
  const [store] = useState(
    () =>
      new ApplicationStore({
        snapshot: api.snapshot,
        onMutation,
        onStopped: (handler) => window.dazedtl.onStopped(handler),
        navigationStorage: {
          getItem: (key) => window.localStorage.getItem(key),
          setItem: (key, value) => window.localStorage.setItem(key, value),
        },
      }),
  );
  useEffect(() => {
    store.start();
    const close = window.dazedtl.onClose(
      async () => {
        document.body.inert = true;
        await flushDrafts();
      },
      () => {
        document.body.inert = false;
      },
    );
    return () => {
      close();
      document.body.inert = false;
      store.stop();
    };
  }, [store]);
  return <Context.Provider value={store}>{children}</Context.Provider>;
}
export function useApplication() {
  const store = useContext(Context);
  if (!store) throw new Error("ApplicationProvider is required.");
  const value = useSyncExternalStore(store.subscribe, store.getSnapshot);
  return { ...value, refresh: store.refresh, settle: store.settle, navigate: store.navigate,
    navigateGuided: store.navigateGuided, clearError: store.clearError };
}
