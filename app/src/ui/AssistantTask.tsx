import { useId, type ReactNode } from "react";
import { ActionRow } from "./ActionList";
import { HelpPopover } from "./HelpPopover";
import { type DisplayState, assistantDisplay } from "./displayStatus";
import { StatusHeading, StatusMark } from "./StatusMark";

/** Where a copied task stands: never copied, copied and awaited, back, or applied. */
export type AssistantTaskState =
  "idle" | "waiting" | "ready" | "applied" | "attention";

export interface AssistantResult {
  id: string;
  title: string;
  /** Where the result stands, in the shared words; its detail says more. */
  state: DisplayState;
  detail?: ReactNode;
  action?: ReactNode;
}

/**
 * The loop every assistant task shares: copy a task, let the assistant work,
 * review what it saves. The copy action lives in the task's footer; this
 * panel shows where the task stands and each result it should return.
 */
export function AssistantTask({
  state,
  progress,
  description,
  help,
  results = [],
  children,
}: {
  state: AssistantTaskState;
  /** A short count beside the state, such as "1 of 3 saved". */
  progress?: string;
  description: ReactNode;
  /** Background on what the task does and does not do. */
  help?: ReactNode;
  results?: AssistantResult[];
  /** Custom result content, for tasks whose results are not rows. */
  children?: ReactNode;
}) {
  const heading = useId();
  return (
    <section
      className="action-list assistant-task"
      aria-labelledby={heading}
      data-state={state}
    >
      <div className="assistant-task-header panel-header">
        <div className="assistant-task-title">
          <h3 id={heading}>Assistant task</h3>
          {help && <HelpPopover label="Assistant task">{help}</HelpPopover>}
          <span className="assistant-task-state">
            <StatusMark state={assistantDisplay[state]} />
            {progress && <span>{progress}</span>}
          </span>
        </div>
        <p>{description}</p>
      </div>
      {results.map((row) => (
        <ActionRow
          key={row.id}
          label={
            <>
              <StatusHeading state={row.state} title={row.title} />
              {row.detail && <small>{row.detail}</small>}
            </>
          }
        >
          {row.action}
        </ActionRow>
      ))}
      {children && <div className="assistant-task-body">{children}</div>}
    </section>
  );
}
