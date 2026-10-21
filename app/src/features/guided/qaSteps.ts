/** Text QA's steps as both methods run them from the page. */

import { api } from "../../api/client";

export type QaStepName = "prepare" | "apply" | "undo" | "reapply" | "choose";
export type QaStepDetails = Parameters<typeof api.guided.qa>[2];
/** How an operation started here ended, from the page's observed state. */
export type OperationEnd = (
  id: string,
) => Promise<{ status: string; message: string }>;

/** Runs one QA step; an apply, undo or reapply is its own checkpoint. */
export async function runQaStep(
  projectId: string,
  name: QaStepName,
  details: QaStepDetails,
  finished: OperationEnd,
) {
  const started = await api.guided.qa(projectId, name, details);
  if (name === "choose" || !started.operation) return;
  const ended = await finished(started.operation.id);
  if (ended.status !== "complete")
    throw new Error(ended.message || "QA did not finish this step.");
}
