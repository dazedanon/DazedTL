import type { ReactNode } from "react";

/**
 * One task's body and its footer controls. The footer places them in one
 * order on every task: supporting actions, the task's own action, then
 * Continue last. The task action is the primary until the task is done, and
 * then Continue is.
 */
export type TaskView = {
  content: ReactNode;
  secondary?: ReactNode;
  action?: ReactNode;
  next?: ReactNode;
  actionContext?: ReactNode;
  /** Overrides the task's title and description, and adds header actions. */
  heading?: { title?: string; description?: string; actions?: ReactNode };
  /** What the save shortcut does on this task, when it has a save. */
  save?: () => void;
};
