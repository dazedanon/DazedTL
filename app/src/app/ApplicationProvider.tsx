import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { ApplicationStore } from "./applicationStore";
import { flushDrafts } from "../state/leaveGuards";

const Context = createContext<ApplicationStore | null>(null);
export function ApplicationProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new ApplicationStore());
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
  return { ...value, refresh: store.refresh, clearError: store.clearError };
}
