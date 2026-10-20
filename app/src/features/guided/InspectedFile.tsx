import { useCallback, useState } from "react";
import { api } from "../../api/client";
import { SegmentedControl } from "../../ui/SegmentedControl";
import { WorkingFileText } from "./WorkingFileText";

/**
 * Keep file search and paging mounted when the inspector changes content
 * tabs. A Database files or Maps & events file with `left` lines still to
 * translate opens on them; all its text is one switch away.
 */
export function InspectedFile({
  projectId,
  file,
  left,
}: {
  projectId: string;
  file: string;
  left?: number;
}) {
  const [view, setView] = useState<"left" | "all">(left ? "left" : "all");
  const shown = left === undefined ? "all" : view;
  const read = useCallback(
    (offset: number, query: string) =>
      api.guided.filePreview(projectId, file, offset, query, shown === "left"),
    [projectId, file, shown],
  );
  return (
    <WorkingFileText
      source={`${projectId}:${file}:${shown}`}
      read={read}
      empty={shown === "left" ? "No lines left in this file." : undefined}
      noun={shown === "left" ? "line" : undefined}
      tools={
        left !== undefined && (
          <SegmentedControl
            label="File text shown"
            value={shown}
            onChange={setView}
            options={[
              { value: "left", label: `Lines left (${left.toLocaleString()})` },
              { value: "all", label: "All text" },
            ]}
          />
        )
      }
    />
  );
}
