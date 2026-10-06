import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** The top bar's screen-action area; the active screen fills it while mounted. */
export const TopbarSlot = createContext<HTMLElement | null>(null);

export function TopbarActions({ children }: { children: ReactNode }) {
  const target = useContext(TopbarSlot);
  return target ? createPortal(children, target) : null;
}
