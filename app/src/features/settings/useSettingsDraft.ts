import { useEffect, useRef } from "react";
import { api } from "../../api/client";
import type { Settings, Value, ConnectionInput } from "../../api/contracts";
import { useDraft } from "../../state/useDraft";
import type { Commit } from "../../state/DraftSession";

const content = (value: Settings) =>
  JSON.stringify({ values: value.values, engines: value.engines });
function changedValues<T>(
  before: Record<string, T>,
  current: Record<string, T>,
  saved: Record<string, T>,
) {
  const result = { ...saved };
  for (const key of new Set([
    ...Object.keys(before),
    ...Object.keys(current),
  ])) {
    if (JSON.stringify(before[key]) === JSON.stringify(current[key])) continue;
    if (key in current) result[key] = current[key];
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
    values: changedValues(
      before.values,
      current.values,
      (result.draft || result.saved).values,
    ),
    engines: changedValues(
      before.engines,
      current.engines,
      (result.draft || result.saved).engines,
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
      .catch(report);
    return () => {
      active = false;
    };
  }, [draft.session]);
  const edit = (name: string, value: Value) => {
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
    flush: draft.session.flush,
    save,
    revert,
    saveConnection: (input: ConnectionInput) =>
      connectionAction((revision) => api.saveConnection(revision, input)),
    selectConnection: (id: string) =>
      connectionAction((revision) => api.selectConnection(revision, id)),
    checkConnection: (id: string) =>
      connectionAction((revision) => api.checkConnection(revision, id)),
  };
}
