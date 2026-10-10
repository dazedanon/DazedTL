/** Text QA's steps as both methods run them from the page. */

import { api } from "../../api/client";

export type QaStepName = "prepare" | "apply" | "undo" | "choose";
export type QaStepDetails = Parameters<typeof api.guided.qa>[2];
/** How an operation started here ended, from the page's observed state. */
export type OperationEnd = (
  id: string,
) => Promise<{ status: string; message: string }>;

/** Saves the game's corrected text as a version. */
export async function saveQaVersion(projectId: string, finished: OperationEnd) {
  const saved = await api.guided.qa(projectId, "checkpoint");
  const committed = await finished(saved.operation!.id);
  if (committed.status !== "complete")
    throw new Error(
      "The corrections are in the game, but their version was not saved: " +
        (committed.message || "the checkpoint did not finish."),
    );
}

/** Runs one QA step; an apply or undo goes on to its checkpoint commit. */
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
  if (name !== "prepare") await saveQaVersion(projectId, finished);
}
