import { Children, type ReactNode } from "react";

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

/** A label beside its actions; every action sits in the shared action column. */
export function ActionRow({
  title,
  description,
  label,
  children,
}: {
  /** The row's name; with `description`, the standard two-line label. */
  title?: ReactNode;
  description?: ReactNode;
  /** A custom label for rows that show more than a name and one line. */
  label?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="action-row">
      <span className="action-row-label">
        {label ?? (
          <>
            {title && <strong>{title}</strong>}
            {description && <small>{description}</small>}
          </>
        )}
      </span>
      {Children.toArray(children).length > 0 && (
        <div className="action-row-actions">{children}</div>
      )}
    </div>
  );
}
