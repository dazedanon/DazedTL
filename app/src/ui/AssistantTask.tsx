import type { ReactNode } from "react";
import { ActionRow } from "./ActionList";
import type { DisplayState } from "./displayStatus";
import { StatusHeading } from "./StatusMark";
import { StatusPanel } from "./StatusPanel";

/**
 * Where a copied task stands, in the shared words. Needs review means a
 * result waits for the user's decision; a result that saved itself is Done
 * or Applied, and one waiting only to go into the game is Ready to apply.
 */
export type AssistantTaskState = Extract<
  DisplayState,
  | "not_started"
  | "waiting"
  | "needs_review"
  | "ready"
  | "applied"
  | "done"
  | "outdated"
  | "blocked"
>;

export interface AssistantResult {
  id: string;
  title: string;
  /**
   * Where the result stands, in the shared words; its detail says more. A
   * result nothing reports back on has no state.
   */
  state?: DisplayState;
  detail?: ReactNode;
  action?: ReactNode;
}

/**
 * The loop every assistant task shares: copy a task, let the assistant work,
 * review what it saves. The copy action lives in the task's footer; this
 * panel shows where the task stands and each result it should return.
 */
export function AssistantTask({
  title = "Assistant task",
  state,
  progress,
  description,
  help,
  results = [],
  children,
}: {
  /** A flow that also holds the user's own steps names itself instead. */
  title?: string;
  state: AssistantTaskState;
  /** A short count beside the state, such as "1 of 3 saved". */
  progress?: string;
  description?: ReactNode;
  /** Background on what the task does and does not do. */
  help?: ReactNode;
  results?: AssistantResult[];
  /** Custom result content, for tasks whose results are not rows. */
  children?: ReactNode;
}) {
  return (
    <StatusPanel
      className="assistant-task"
      title={title}
      state={state}
      progress={progress}
      description={description}
      help={help}
    >
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
      {children && <div className="status-panel-body">{children}</div>}
    </StatusPanel>
  );
}
