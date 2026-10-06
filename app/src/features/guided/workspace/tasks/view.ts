import type { ReactNode } from "react";

/** One task's body and the footer controls placed beside its context. */
export type TaskView = {
  content: ReactNode;
  primary?: ReactNode;
  secondary?: ReactNode;
  actionContext?: ReactNode;
};
