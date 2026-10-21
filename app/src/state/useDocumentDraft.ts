import type { Documents } from "../api/contracts";
import { saveDocument } from "./documentSave";
import { useDraft } from "./useDraft";

export function useDocumentDraft(
  identity: string,
  recovered: Documents,
  report: (error: unknown) => void,
  adapter: {
    persist: (documents: Documents) => Promise<unknown>;
    save: (name: string, revision: string, text: string) => Promise<Documents>;
  },
) {
  const draft = useDraft<Documents>(identity, {
    persist: adapter.persist,
    report,
    initial: { saved: {}, draft: recovered },
  });
  function edit(name: string, text: string, revision: string) {
    draft.session.edit((current) => ({
      ...current,
      [name]: { text, revision },
    }));
  }
  const save = (name: string, created?: Documents[string]) =>
    saveDocument(draft.session, adapter.save, name, created);
  async function discard(name: string) {
    draft.session.edit((current) => {
      const pending = { ...current };
      delete pending[name];
      return pending;
    });
    await draft.session.flush();
  }
  return {
    drafts: draft.value || recovered,
    committing: draft.committing,
    edit,
    save,
    discard,
  };
}
