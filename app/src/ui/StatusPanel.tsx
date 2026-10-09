import { useId, type ReactNode } from "react";
import { HelpPopover } from "./HelpPopover";
import type { DisplayState } from "./displayStatus";
import { StatusMark } from "./StatusMark";

/**
 * A panel whose first row names it and where it stands, with a line on what
 * happens next when there is one, such as an assistant task or an API run. Its content follows
 * as rows, or inside a `status-panel-body`.
 */
export function StatusPanel({
  title,
  state,
  progress,
  description,
  help,
  className = "",
  children,
}: {
  title: string;
  state: DisplayState;
  /** A short note beside the state, such as "1 of 3 saved". */
  progress?: string;
  description?: ReactNode;
  /** Background on what the panel shows and does not show. */
  help?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  const heading = useId();
  return (
    <section
      className={`action-list status-panel ${className}`.trim()}
      aria-labelledby={heading}
      data-state={state}
    >
      <div className="status-panel-header panel-header">
        <div className="status-panel-title">
          <h3 id={heading}>{title}</h3>
          {help && <HelpPopover label={title}>{help}</HelpPopover>}
          <span className="status-panel-state">
            <StatusMark state={state} />
            {progress && <span>{progress}</span>}
          </span>
        </div>
        {description && <p>{description}</p>}
      </div>
      {children}
    </section>
  );
}
