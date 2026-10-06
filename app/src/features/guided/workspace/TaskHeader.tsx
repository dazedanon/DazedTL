import type { ReactNode, Ref } from "react";

/** The one heading every Guided task starts with: its name, purpose and own actions. */
export function TaskHeader({
  title,
  description,
  actions,
  headingRef,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  headingRef: Ref<HTMLHeadingElement>;
}) {
  return (
    <header className="task-header">
      <div className="task-header-text">
        <h2 ref={headingRef} tabIndex={-1}>
          {title}
        </h2>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}
