import { useEffect, useEffectEvent, useRef } from "react";
import { api } from "../../api/client";
import type { ProjectOptions, TranslationState } from "../../api/contracts";
import { useDraft } from "../../state/useDraft";

type Value = Pick<ProjectOptions, "options" | "revision">;
export function useProjectOptions(
  state: TranslationState,
  report: (error: unknown) => void,
) {
  const saved: Value = { options: state.options, revision: state.revision };
  const draft = useDraft<Value>("translation-options:" + state.projectId, {
    initial: { saved, draft: state.drafts.options || undefined },
    report,
    persist: (value) =>
      api.translation.draft(state.projectId, "options", value),
  });
  // A newer saved revision replaces the draft once it is clean and idle.
  const adoptSaved = useEffectEvent(() => draft.session.adopt(saved));
  const observed = useRef(state.revision);
  const pending = useRef(false);
  useEffect(() => {
    if (observed.current !== state.revision) {
      observed.current = state.revision;
      pending.current = true;
    }
    if (pending.current && !draft.dirty && !draft.committing) {
      pending.current = false;
      adoptSaved();
    }
  }, [state.revision, draft.dirty, draft.committing]);
  async function save() {
    await draft.session.commit(
      async (value) => {
        const result = await api.translation.save(
          state.projectId,
          value.revision,
          value.options,
        );
        return {
          saved: { options: result.options, revision: result.revision },
        };
      },
      (_before, current, result) => ({
        ...current,
        revision: result.saved.revision,
      }),
    );
  }
  async function discard() {
    await api.translation.draft(state.projectId, "options", null);
    draft.session.adopt(saved);
  }
  return { ...draft, value: draft.value || saved, save, discard };
}
