import { useCallback } from "react";
import { api } from "../../api/client";
import { WorkingFileText } from "./WorkingFileText";

/** Keep file search and paging mounted when the inspector changes content tabs. */
export function InspectedFile({ projectId, file }: { projectId: string; file: string }) {
  const read = useCallback((offset: number, query: string) => api.guided.filePreview(projectId, file, offset, query), [projectId, file]);
  return <WorkingFileText read={read} />;
}
