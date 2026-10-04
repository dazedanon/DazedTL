import type { Documents } from "../api/contracts";
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
  async function save(name: string) {
    let documents: Documents = {};
    await draft.session.commit(
      async (current) => {
        const document = current[name];
        if (!document) return { saved: {}, draft: current };
        documents = await adapter.save(name, document.revision, document.text);
        const pending = { ...current };
        delete pending[name];
        return { saved: {}, draft: pending };
      },
      (before, current) => {
        const pending = { ...current };
        if (JSON.stringify(before[name]) === JSON.stringify(current[name]))
          delete pending[name];
        else if (pending[name] && documents[name])
          pending[name] = {
            ...pending[name],
            revision: documents[name].revision,
          };
        return pending;
      },
    );
    return documents;
  }
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
