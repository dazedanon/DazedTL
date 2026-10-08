import { useEffect, useEffectEvent, useRef } from "react";
import type { GuidedState } from "../../api/contracts";
import { api } from "../../api/client";
import { useDraft } from "../../state/useDraft";
import {
  mergeInvestigationSettings,
  onlyInvestigationSettingsChanged,
} from "./speakerSetup";
import { advanced } from "./workspace/model";

export function useGuidedWorkflow(
  state: GuidedState,
  report: (error: unknown) => void,
) {
  const saved = state.preferences;
  const draft = useDraft("guided-options:" + state.projectId, {
    initial: { saved, draft: state.optionsDraft || undefined },
    persist: (value) => api.guided.draft(state.projectId, value),
    report,
  });
  const observed = useRef(saved);
  // Reconciles a newer saved revision with the draft; runs when either changes.
  const reconcileSaved = useEffectEvent(() => {
    if (observed.current.revision === saved.revision || draft.committing)
      return;
    const before = observed.current;
    if (!draft.dirty) {
      observed.current = saved;
      draft.session.adopt(saved);
    } else if (draft.value?.revision === saved.revision)
      observed.current = saved;
    else if (
      onlyInvestigationSettingsChanged(before, saved, [
        ...state.speakerSetup.rules.map((rule) => rule.key),
        ...advanced,
      ])
    ) {
      observed.current = saved;
      // The investigation may save settings while a just-typed edit is
      // still waiting for its recovery write. Rebase through the same queue.
      void draft.session
        .commit(
          async (current) => ({
            saved,
            draft: mergeInvestigationSettings(before, current, saved),
          }),
          (_before, current) =>
            mergeInvestigationSettings(before, current, saved),
        )
        .then(async () => {
          if (draft.session.getSnapshot().dirty) {
            draft.session.edit((current) => current);
            await draft.session.flush();
          }
        })
        .catch(report);
    }
  });
  useEffect(
    () => reconcileSaved(),
    [saved.revision, draft.dirty, draft.committing],
  );
  const save = () =>
    draft.session.commit(
      async (value) => ({
        saved: await api.guided.save(
          state.projectId,
          value.revision,
          value.values,
        ),
      }),
      (_before, current, result) => ({
        ...current,
        revision: result.saved.revision,
      }),
    );
  const discard = async () => {
    await api.guided.draft(state.projectId, null);
    draft.session.adopt(saved);
  };
  const applySpeakers = (reset = false) =>
    draft.session.commit(
      async (value) => {
        if (draft.session.getSnapshot().dirty)
          throw new Error(
            "Save or discard your option edits before applying speaker findings.",
          );
        if (!state.speakerSetup.reportId)
          throw new Error("Wait for the setup task’s speaker findings.");
        return {
          saved: await api.guided.applySpeakers(
            state.projectId,
            value.revision,
            state.speakerSetup.reportId,
            reset,
          ),
        };
      },
      (before, current, result) =>
        mergeInvestigationSettings(before, current, result.saved),
    );
  const applyEventText = () =>
    draft.session.commit(
      async (value) => {
        if (draft.session.getSnapshot().dirty)
          throw new Error(
            "Save or discard your option edits before applying event text findings.",
          );
        if (!state.eventText.reportId)
          throw new Error("Wait for the investigation's findings.");
        return {
          saved: await api.guided.eventTextApply(
            state.projectId,
            value.revision,
            state.eventText.reportId,
          ),
        };
      },
      (before, current, result) =>
        mergeInvestigationSettings(before, current, result.saved),
    );
  return {
    ...draft,
    value: draft.value || saved,
    save,
    discard,
    applySpeakers,
    applyEventText,
  };
}
