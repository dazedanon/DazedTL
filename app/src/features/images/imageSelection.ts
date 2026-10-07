import { displayLabels, imageDisplay } from "../../ui/displayStatus.ts";
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

export const imageClassificationLabels: Record<string, string> = {
  recommended: "Recommended",
  uncertain: "Uncertain",
  no_text: "No text found",
  already_english: "Already English",
  not_examined: "Not examined",
  excluded: "Excluded",
};
/** What the shared word for an image's state leaves out: what blocks it, who
 * reviewed it, or what discovery found. */
export function imageReason(asset: ImageAsset) {
  const reason =
    asset.blockedReason ||
    asset.sourceIssue ||
    (asset.aiReviewed
      ? asset.userReviewed
        ? "AI and user reviewed"
        : "AI reviewed"
      : asset.userReviewed
        ? "User reviewed"
        : asset.editable && asset.state === "editable"
          ? "Editable copy made"
          : imageClassificationLabels[asset.classification] || "");
  return reason === displayLabels[imageDisplay(asset)] ? "" : reason;
}
/** An image's state in the shared words, then its reason. */
export function imageStatus(asset: ImageAsset) {
  const state = displayLabels[imageDisplay(asset)];
  const reason = imageReason(asset);
  return reason ? `${state} · ${reason}` : state;
}
