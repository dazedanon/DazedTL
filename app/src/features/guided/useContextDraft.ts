import { api } from "../../api/client";
import type { Documents } from "../../api/contracts";
import { useDocumentDraft } from "../../state/useDocumentDraft";

export function useContextDraft(
  projectId: string,
  recovered: Documents,
  report: (error: unknown) => void,
) {
  return useDocumentDraft("context:" + projectId, recovered, report, {
    persist: (documents) => api.draft(projectId, documents),
    save: (name, revision, text) =>
      api.saveDocument(projectId, name, revision, text),
  });
}
