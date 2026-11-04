import type {
  DocumentDrafts,
  Documents,
  DocumentsSaved,
} from "../api/contracts";
import { saveDocuments } from "./documentSave";
import { useDraft } from "./useDraft";

export function useDocumentDraft(
  identity: string,
  recovered: DocumentDrafts,
  report: (error: unknown) => void,
  adapter: {
    persist: (documents: DocumentDrafts) => Promise<unknown>;
    save: (documents: DocumentDrafts) => Promise<DocumentsSaved>;
  },
) {
  const draft = useDraft<DocumentDrafts>(identity, {
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
  /** Keeps the drafts of `names` over their files as they are now: each
   * takes its file's current revision, so saving it replaces the file. */
  function rebase(names: string[], documents: Documents) {
    draft.session.edit((current) => {
      const next = { ...current };
      for (const name of names)
        if (next[name] && documents[name])
          next[name] = { ...next[name], revision: documents[name].revision };
      return next;
    });
  }
  const save = (names: string[]) =>
    saveDocuments(draft.session, adapter.save, names);
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
    rebase,
    save,
    discard,
  };
}
