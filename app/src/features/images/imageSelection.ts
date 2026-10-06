import type {
  ImageAsset,
  ImageDraft,
  ImageManagerState,
} from "../../api/contracts";

export function imageDraft(state: ImageManagerState): ImageDraft {
  return {
    selection: state.selection || [],
    view: Object.assign(
      {
        query: "",
        status: "all",
        folder: "",
        showSelected: false,
        tileSize: 112,
        scroll: 0,
      },
      state.view,
    ),
    discoveryScope: state.discovery.scope || "all",
    folders: state.discovery.folders || [],
  };
}

export function toggleImage(
  selection: readonly string[],
  id: string,
  checked: boolean,
) {
  const next = new Set(selection);
  if (checked) next.add(id);
  else next.delete(id);
  return [...next];
}

export function virtualRows(
  total: number,
  columns: number,
  rowHeight: number,
  scroll: number,
  height: number,
  overscan = 2,
) {
  const count = Math.ceil(total / Math.max(1, columns));
  const first = Math.max(
    0,
    Math.min(
      Math.max(0, count - 1),
      Math.floor(Math.max(0, scroll) / rowHeight) - overscan,
    ),
  );
  const last = Math.min(
    count,
    Math.max(
      first + 1,
      Math.ceil((Math.max(0, scroll) + height) / rowHeight) + overscan,
    ),
  );
  return {
    start: first * columns,
    end: Math.min(total, last * columns),
    top: first * rowHeight,
    height: count * rowHeight,
  };
}

export const imageStateLabels: Record<string, string> = {
  not_prepared: "Not prepared",
  editable: "Editable",
  editing: "Editing",
  needs_review: "Needs review",
  approved: "Ready",
  ready: "Ready",
  applied: "Applied",
  skipped: "Skipped",
  conflict: "Conflict",
  missing_source: "Missing source",
  error: "Error",
  blocked: "Blocked",
};
export const imageClassificationLabels: Record<string, string> = {
  recommended: "Recommended",
  uncertain: "Uncertain",
  no_text: "No text found",
  already_english: "Already English",
  not_examined: "Not examined",
  excluded: "Excluded",
};
export function imageStatus(asset: ImageAsset) {
  if (
    asset.sourceIssue ||
    ["blocked", "conflict", "error", "missing_source"].includes(asset.state)
  )
    return asset.blockedReason || asset.sourceIssue || "Blocked";
  if (asset.aiReviewed)
    return asset.userReviewed ? "AI and user reviewed" : "AI reviewed";
  if (asset.userReviewed) return "User reviewed";
  return (
    imageStateLabels[asset.state] ||
    imageClassificationLabels[asset.classification] ||
    asset.state
  );
}
