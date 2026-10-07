import type { AssistantTaskKind } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import {
  type AssistantSources,
  assistantTasks,
  assistantWaiting,
} from "./assistantTasks";

/** The current project's copied tasks and the feature states they read. */
export function useAssistantSources(): AssistantSources | null {
  const snapshot = useApplication().snapshot;
  const project = snapshot?.application.project;
  if (!snapshot || !project) return null;
  const own = <T extends { projectId: string }>(value?: T | null) =>
    value && value.projectId === project.id ? value : null;
  return {
    records: snapshot.assistantTasks,
    method: project.method,
    guided: own(snapshot.guided),
    images: own(snapshot.images),
    plugins: own(snapshot.plugins),
  };
}

export function useAssistantTasks() {
  const sources = useAssistantSources();
  return sources ? assistantTasks(sources) : [];
}

/** Whether one task waits on the assistant, for its feature's own panel. */
export function useHandoff(kind: AssistantTaskKind) {
  const sources = useAssistantSources();
  return sources
    ? assistantWaiting(kind, sources)
    : { waiting: false, dismissed: false, since: "" };
}
