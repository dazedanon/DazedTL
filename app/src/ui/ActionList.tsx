import { Children, useId, type ReactNode } from "react";

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

/**
 * A label beside its actions; every action sits in the shared action column.
 * A named row with actions is a group, so rows that share button labels,
 * such as Install, still tell them apart.
 */
export function ActionRow({
  title,
  description,
  label,
  name,
  children,
}: {
  /** The row's name; with `description`, the standard two-line label. */
  title?: ReactNode;
  description?: ReactNode;
  /** A custom label for rows that show more than a name and one line. */
  label?: ReactNode;
  /** The row's name beside a custom label, which names its actions. */
  name?: string;
  children?: ReactNode;
}) {
  const id = useId();
  const actions = Children.toArray(children).length > 0;
  const titled = !label && !!title;
  const group = actions && (!!name || titled);
  return (
    <div
      className="action-row"
      role={group ? "group" : undefined}
      aria-label={group ? name : undefined}
      aria-labelledby={group && !name ? id : undefined}
    >
      <span className="action-row-label">
        {label ?? (
          <>
            {title && <strong id={id}>{title}</strong>}
            {description && <small>{description}</small>}
          </>
        )}
      </span>
      {actions && <div className="action-row-actions">{children}</div>}
    </div>
  );
}
