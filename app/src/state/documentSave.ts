import type { Documents } from "../api/contracts";
import type { DraftSession } from "./DraftSession";

/**
 * Saves the drafts of `names` in one save, with `created`, the text of
 * documents that have no file yet, which never become drafts: a refused save
 * leaves nothing unsaved the user didn't edit.
 */
export async function saveDocuments(
  session: DraftSession<Documents>,
  save: (documents: Documents) => Promise<Documents>,
  names: string[],
  created: Documents = {},
) {
  let documents: Documents = {};
  await session.commit(
    async (current) => {
      const chosen: Documents = {};
      for (const name of names) {
        const document = current[name] ?? created[name];
        if (document) chosen[name] = document;
      }
      if (!Object.keys(chosen).length) return { saved: {}, draft: current };
      documents = await save(chosen);
      const pending = { ...current };
      for (const name of names) delete pending[name];
      return { saved: {}, draft: pending };
    },
    (before, current) => {
      const pending = { ...current };
      for (const name of names) {
        if (JSON.stringify(before[name]) === JSON.stringify(current[name]))
          delete pending[name];
        else if (pending[name] && documents[name])
          pending[name] = {
            ...pending[name],
            revision: documents[name].revision,
          };
      }
      return pending;
    },
  );
  return documents;
}
