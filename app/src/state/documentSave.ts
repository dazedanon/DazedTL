import type { Documents } from "../api/contracts";
import type { DraftSession } from "./DraftSession";

/**
 * Saves one document's draft, or `created`, the text of a document that has
 * no file yet, which never becomes a draft: a refused save leaves nothing
 * unsaved the user didn't edit.
 */
export async function saveDocument(
  session: DraftSession<Documents>,
  save: (name: string, revision: string, text: string) => Promise<Documents>,
  name: string,
  created?: Documents[string],
) {
  let documents: Documents = {};
  await session.commit(
    async (current) => {
      const document = current[name] ?? created;
      if (!document) return { saved: {}, draft: current };
      documents = await save(name, document.revision, document.text);
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
