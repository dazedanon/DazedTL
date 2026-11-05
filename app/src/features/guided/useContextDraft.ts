import { api } from "../../api/client";
import type { DocumentDrafts } from "../../api/contracts";
import { useDocumentDraft } from "../../state/useDocumentDraft";

export function useContextDraft(
  projectId: string,
  recovered: DocumentDrafts,
  report: (error: unknown) => void,
) {
  return useDocumentDraft("context:" + projectId, recovered, report, {
    persist: (documents) => api.draft(projectId, documents),
    save: (documents) => api.saveDocuments(projectId, documents),
  });
}
