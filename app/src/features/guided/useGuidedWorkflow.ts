import { useEffect, useRef } from "react";
import type { GuidedState } from "../../api/contracts";
import { api } from "../../api/client";
import { useDraft } from "../../state/useDraft";

export function useGuidedWorkflow(state: GuidedState, report: (error: unknown) => void) {
  const saved = state.preferences;
  const draft = useDraft("guided-options:" + state.projectId, {
    initial: { saved, draft: state.optionsDraft || undefined },
    persist: (value) => api.guided.draft(state.projectId, value),
    report,
  });
  const observed = useRef(saved.revision);
  useEffect(() => {
    if (observed.current !== saved.revision && !draft.dirty && !draft.committing) {
      observed.current = saved.revision;
      draft.session.adopt(saved);
    }
  }, [saved.revision, draft.dirty, draft.committing]);
  const save = () => draft.session.commit(async (value) => ({
    saved: await api.guided.save(state.projectId, value.revision, value.values),
  }), (_before, current, result) => ({ ...current, revision: result.saved.revision }));
  const discard = async () => {
    await api.guided.draft(state.projectId, null);
    draft.session.adopt(saved);
  };
  return { ...draft, value: draft.value || saved, save, discard };
}
