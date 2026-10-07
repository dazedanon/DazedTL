import { useEffect, useEffectEvent, useRef } from "react";
import { api } from "../../api/client";
import type {
  Settings,
  PreferenceValues,
  ModelOptions,
  ConnectionInput,
} from "../../api/contracts";
import { useDraft } from "../../state/useDraft";
import type { Commit } from "../../state/DraftSession";
import { onSettingsSaved } from "./settingsChanges";

const content = (value: Settings) =>
  JSON.stringify({ values: value.values, modelOptions: value.modelOptions });
function changedValues<T extends object>(before: T, current: T, saved: T) {
  const result = { ...saved };
  for (const key of new Set([
    ...(Object.keys(before) as (keyof T)[]),
    ...(Object.keys(current) as (keyof T)[]),
  ])) {
    if (JSON.stringify(before[key]) === JSON.stringify(current[key])) continue;
    if (Object.hasOwn(current, key))
      Object.defineProperty(result, key, {
        value: current[key],
        enumerable: true,
        writable: true,
        configurable: true,
      });
    else delete result[key];
  }
  return result;
}
function reconcile(
  before: Settings,
  current: Settings,
  result: Commit<Settings>,
): Settings {
  return {
    ...result.saved,
    values: {
      ...(result.draft || result.saved).values,
      ...changedValues(
        before.values,
        current.values,
        (result.draft || result.saved).values,
      ),
    },
    modelOptions: changedValues(
      before.modelOptions,
      current.modelOptions,
      (result.draft || result.saved).modelOptions,
    ),
  };
}
export function useSettingsDraft(report: (error: unknown) => void) {
  const saved = useRef<Settings | null>(null);
  const changingConnection = useRef(false);
  const draft = useDraft<Settings>("settings", {
    persist: api.settingsDraft,
    report,
    fingerprint: content,
  });
  function split(value: Settings, recover = false): Commit<Settings> {
    const { draft, ...baseline } = value;
    saved.current = baseline;
    return {
      saved: baseline,
      draft: recover && draft ? { ...baseline, ...draft } : undefined,
    };
  }
  const reportLoad = useEffectEvent((error: unknown) => report(error));
  useEffect(() => {
    let active = true;
    api
      .settings()
      .then((value) => {
        if (active) {
          const loaded = split(value, true);
          draft.session.adopt(loaded.saved, loaded.draft);
        }
      })
      .catch(reportLoad);
    return () => {
      active = false;
    };
  }, [draft.session]);
  // A save from elsewhere replaces a clean page; pending edits keep theirs and
  // meet the revision check when saved.
  const reload = useEffectEvent(() => {
    if (draft.dirty || draft.committing) return;
    api
      .settings()
      .then((value) => {
        const loaded = split(value, true);
        draft.session.adopt(loaded.saved, loaded.draft);
      })
      .catch(reportLoad);
  });
  useEffect(() => onSettingsSaved(() => reload()), []);
  const edit = (name: keyof PreferenceValues, value: string) => {
    if (changingConnection.current) return;
    draft.session.edit((current) => ({
      ...current,
      values: { ...current.values, [name]: value },
    }));
  };
  const save = () =>
    draft.session.commit(
      async (current) => split(await api.saveSettings(current)),
      reconcile,
    );
  const revert = () =>
    draft.session.commit(async () => {
      if (!saved.current) throw new Error("Wait for settings to load.");
      return split(await api.revertSettings(saved.current));
    }, reconcile);
  async function connectionAction(
    operation: (revision: number) => Promise<Settings>,
  ) {
    changingConnection.current = true;
    try {
      return await draft.session.commit(
        async (current) => split(await operation(current.revision), true),
        reconcile,
      );
    } finally {
      changingConnection.current = false;
    }
  }
  return {
    config: draft.value || null,
    dirty: draft.dirty,
    committing: draft.committing,
    edit,
    editModelOptions: (model: string, value: ModelOptions) => {
      if (changingConnection.current || !model.trim()) return;
      draft.session.edit((current) => ({
        ...current,
        modelOptions: { ...current.modelOptions, [model.trim()]: value },
      }));
    },
    flush: draft.session.flush,
    save,
    revert,
    saveConnection: (input: ConnectionInput) =>
      connectionAction((revision) => api.saveConnection(revision, input)),
    selectConnection: (id: string) =>
      connectionAction((revision) => api.selectConnection(revision, id)),
    checkConnection: (id: string) =>
      connectionAction((revision) => api.checkConnection(revision, id)),
    removeConnection: (id: string, unfinished: number) =>
      connectionAction((revision) =>
        api.removeConnection(revision, id, unfinished),
      ),
  };
}
