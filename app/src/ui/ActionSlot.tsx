import type { ReactNode } from "react";
import { createPortal } from "react-dom";

/** Embedded utility pages can use their host's footer outside its scroll area. */
export function ActionSlot({ target, children }: { target?: HTMLElement | null; children: ReactNode }) {
  return target ? createPortal(children, target) : <div className="actions">{children}</div>;
}
