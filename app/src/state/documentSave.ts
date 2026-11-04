import type { DocumentDrafts, DocumentsSaved } from "../api/contracts";
import type { DraftSession } from "./DraftSession";

/**
 * Saves the drafts of `names` in one save and returns the backend's reply:
 * the documents, and the names it wrote. Drafts edited while it saved stay,
 * at the revision the save left their file at.
 */
export async function saveDocuments(
  session: DraftSession<DocumentDrafts>,
  save: (documents: DocumentDrafts) => Promise<DocumentsSaved>,
  names: string[],
) {
  let result: DocumentsSaved = { documents: {}, saved: [] };
  await session.commit(
    async (current) => {
      const chosen: DocumentDrafts = {};
      for (const name of names) if (current[name]) chosen[name] = current[name];
      result = await save(chosen);
      const pending = { ...current };
      for (const name of names) delete pending[name];
      return { saved: {}, draft: pending };
    },
    (before, current) => {
      const pending = { ...current };
      for (const name of names) {
        if (JSON.stringify(before[name]) === JSON.stringify(current[name]))
          delete pending[name];
        else if (pending[name] && result.documents[name])
          pending[name] = {
            ...pending[name],
            revision: result.documents[name].revision,
          };
      }
      return pending;
    },
  );
  return result;
}
