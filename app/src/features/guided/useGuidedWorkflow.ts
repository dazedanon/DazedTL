import { useEffect, useRef, useState } from "react";
import type { Project, RunMode } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";

export function useGuidedWorkflow(project: Project) {
  const application = useApplication();
  const state =
    application.snapshot?.guided?.projectId === project.id
      ? application.snapshot.guided
      : null;
  const action = useAction({ after: application.refresh });
  const initialized = useRef(state ? project.id : "");
  const [stage, setStage] = useState(
    state?.importedFiles.length ? "translate" : "files",
  );
  const [selected, setSelected] = useState<string[]>(state?.selection || []);
  const [mode, setMode] = useState<RunMode>(
    state?.provider.defaultMode || "estimate",
  );
  useEffect(() => {
    if (!state || initialized.current === project.id) return;
    initialized.current = project.id;
    setSelected(state.selection);
    setMode(state.provider.defaultMode);
    setStage(state.importedFiles.length ? "translate" : "files");
  }, [state, project.id]);
  const move = (next: string) =>
    action.run(async () => {
      await flushDrafts();
      setStage(next);
    });
  return {
    state,
    action,
    stage,
    selected,
    setSelected,
    mode,
    setMode,
    move,
    refresh: application.refresh,
    running: !!application.snapshot?.application.running,
  };
}
