/** The background record of the open game's original files, which a write
 * that changes them waits for (original_record.py). A failure saying so
 * shows the record instead, wherever it is shown (Feedback.tsx). */
import { createContext, useContext, type ReactNode } from "react";
import type { OriginalRecord } from "../api/contracts";

const Context = createContext<{
  record?: OriginalRecord;
  stop: () => Promise<unknown>;
}>({ stop: async () => undefined });

export function OriginalRecordProvider({
  record,
  stop,
  children,
}: {
  record?: OriginalRecord;
  stop: () => Promise<unknown>;
  children: ReactNode;
}) {
  return (
    <Context.Provider value={{ record, stop }}>{children}</Context.Provider>
  );
}

/** The open game's original record, as a write waiting for it shows it. */
export function useOriginalRecord() {
  return useContext(Context);
}
