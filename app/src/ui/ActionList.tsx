import type { ReactNode } from "react";

export function ActionList({ children }: { children: ReactNode }) {
  return <div className="action-list">{children}</div>;
}

export function ActionRow({ label, children }: { label: ReactNode; children: ReactNode }) {
  return <div className="action-row">
    <span className="action-row-label">{label}</span>
    {children}
  </div>;
}
