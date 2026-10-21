import type { Documents } from "../api/contracts";
import { saveDocuments } from "./documentSave";
import { useDraft } from "./useDraft";

export function useDocumentDraft(
  identity: string,
  recovered: Documents,
  report: (error: unknown) => void,
  adapter: {
    persist: (documents: Documents) => Promise<unknown>;
    save: (documents: Documents) => Promise<Documents>;
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
  // `created` holds the text of documents that have no file yet.
  const save = (names: string[], created?: Documents) =>
    saveDocuments(draft.session, adapter.save, names, created);
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
