import type { ReactNode } from "react";

/** One task's body and the footer controls placed beside its context. */
export type TaskView = {
  content: ReactNode;
  primary?: ReactNode;
  secondary?: ReactNode;
  actionContext?: ReactNode;
  /** Overrides the task's title and description, and adds header actions. */
  heading?: { title?: string; description?: string; actions?: ReactNode };
};
