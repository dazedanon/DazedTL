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

/** The most images one list read returns. */
const READ_LIMIT = 500;
/**
 * The ids of images `first` to `last` in grid order, for a Shift range that
 * reaches past the loaded pages. Loaded images answer at once; the rest are
 * read in runs the list allows.
 */
export function idsBetween(
  first: number,
  last: number,
  loaded: (index: number) => string | undefined,
  read: (offset: number, limit: number) => Promise<string[]>,
): string[] | Promise<string[]> {
  const ids: string[] = [];
  for (let index = first; index <= last; index++) {
    const id = loaded(index);
    if (id === undefined) return readFrom(ids, index, last, loaded, read);
    ids.push(id);
  }
  return ids;
}
async function readFrom(
  ids: string[],
  index: number,
  last: number,
  loaded: (index: number) => string | undefined,
  read: (offset: number, limit: number) => Promise<string[]>,
) {
  while (index <= last) {
    const id = loaded(index);
    if (id !== undefined) {
      ids.push(id);
      index++;
      continue;
    }
    let limit = 1;
    while (
      limit < READ_LIMIT &&
      index + limit <= last &&
      loaded(index + limit) === undefined
    )
      limit++;
    const page = await read(index, limit);
    ids.push(...page);
    // A shorter list ends the range where the images end.
    if (page.length < limit) break;
    index += limit;
  }
  return ids;
}

/** The tile an arrow, Home or End key moves to, or null for other keys. */
export function gridStep(
  key: string,
  index: number,
  columns: number,
  total: number,
) {
  const last = total - 1;
  switch (key) {
    case "ArrowLeft":
      return Math.max(0, index - 1);
    case "ArrowRight":
      return Math.min(last, index + 1);
    case "ArrowUp":
      return index >= columns ? index - columns : index;
    case "ArrowDown":
      // From a full row into a shorter last one, the move ends on its last tile.
      return Math.floor(index / columns) < Math.floor(last / columns)
        ? Math.min(last, index + columns)
        : index;
    case "Home":
      return 0;
    case "End":
      return last;
    default:
      return null;
  }
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
export function imageReason(asset: ImageAsset, listed = false) {
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
  return reason === displayLabels[imageDisplay(asset, listed)] ? "" : reason;
}
/** An image's state in the shared words, then its reason. */
export function imageStatus(asset: ImageAsset, listed = false) {
  const state = displayLabels[imageDisplay(asset, listed)];
  const reason = imageReason(asset, listed);
  return reason ? `${state} · ${reason}` : state;
}
