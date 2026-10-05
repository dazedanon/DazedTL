import type { ReactNode } from "react";

export function ActionList({
  children,
  compact = false,
}: {
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`action-list${compact ? " action-list--compact" : ""}`}>
      {children}
    </div>
  );
}

export function ActionRow({
  label,
  children,
}: {
  label: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="action-row">
      <span className="action-row-label">{label}</span>
      {children}
    </div>
  );
}
