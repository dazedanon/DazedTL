import type { AssistantTaskKind } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import {
  type AssistantSources,
  assistantSources,
  assistantTasks,
  assistantWaiting,
  noHandoff,
} from "./assistantTasks";

/** The current project's copied tasks and the feature states they read. */
export function useAssistantSources(): AssistantSources | null {
  const snapshot = useApplication().snapshot;
  return snapshot ? assistantSources(snapshot) : null;
}

export function useAssistantTasks() {
  const sources = useAssistantSources();
  return sources ? assistantTasks(sources) : [];
}

/** Whether one task waits on the assistant, for its feature's own panel. */
export function useHandoff(kind: AssistantTaskKind) {
  const sources = useAssistantSources();
  return sources ? assistantWaiting(kind, sources) : noHandoff;
}
