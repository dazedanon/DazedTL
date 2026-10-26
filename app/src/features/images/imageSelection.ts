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

/**
 * The choices a reply saved, with the user's edits made while it was on its
 * way replayed on top: images ticked or unticked since, and changed view
 * settings. Keeping the edited draft whole would save over what the reply
 * brought, such as an assistant's newly ticked recommendations.
 */
export function rebaseImageDraft(
  before: ImageDraft,
  current: ImageDraft,
  saved: ImageDraft,
): ImageDraft {
  const had = new Set(before.selection);
  const has = new Set(current.selection);
  const added = current.selection.filter((id) => !had.has(id));
  const removed = new Set(before.selection.filter((id) => !has.has(id)));
  const changed = <K extends keyof ImageDraft>(key: K) =>
    JSON.stringify(current[key]) !== JSON.stringify(before[key]);
  return {
    ...saved,
    selection: [
      ...new Set(
        [...saved.selection, ...added].filter((id) => !removed.has(id)),
      ),
    ],
    view: {
      ...saved.view,
      ...Object.fromEntries(
        Object.entries(current.view).filter(
          ([key, item]) =>
            item !== before.view[key as keyof ImageDraft["view"]],
        ),
      ),
    },
    discoveryScope: changed("discoveryScope")
      ? current.discoveryScope
      : saved.discoveryScope,
    folders: changed("folders") ? current.folders : saved.folders,
  };
}

/**
 * The parts of a draft that differ from the saved choices. A scroll, a filter
 * or a preview changes only the view, so its save leaves the list to
 * translate alone instead of checking and rewriting every ticked image.
 */
export function draftChanges(
  saved: ImageDraft,
  draft: ImageDraft,
): Partial<ImageDraft> {
  return Object.fromEntries(
    Object.entries(draft).filter(
      ([key, item]) =>
        JSON.stringify(item) !== JSON.stringify(saved[key as keyof ImageDraft]),
    ),
  );
}

/** Whether two lists to translate hold the same images, in any order. */
export function sameImages(a: readonly string[], b: readonly string[]) {
  const ids = new Set(a);
  return ids.size === new Set(b).size && b.every((id) => ids.has(id));
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

// Sound effects lettered into scene art are flavor, often hundreds per game:
// an image with nothing else is found "Sound effects only" and stays out of
// the list like a text-free one.
// already_english keeps the name saved findings have; it is text already in
// the game's target language.
export const imageClassificationLabel = (
  classification: string,
  target: string,
): string =>
  ({
    recommended: "Recommended",
    uncertain: "Uncertain",
    no_text: "No text found",
    already_english: `Already in ${target}`,
    sound_effects: "Sound effects only",
    not_examined: "Not examined",
    excluded: "Excluded",
  })[classification] || "";
/** What the shared word for an image's state leaves out: what blocks it, who
 * reviewed it, or what discovery found, in a game translated into *target*. */
export function imageReason(
  asset: ImageAsset,
  listed: boolean,
  target: string,
) {
  const display = imageDisplay(asset, listed);
  // The backend notes what each image's next step needs; it explains a
  // blocked or unreviewed image, and before then the copied translation task
  // takes those steps itself, so what discovery found says more.
  const reason =
    (display === "blocked" || asset.state === "needs_review"
      ? asset.blockedReason
      : "") ||
    asset.sourceIssue ||
    (asset.aiReviewed
      ? asset.userReviewed
        ? "AI and user reviewed"
        : "AI reviewed"
      : asset.userReviewed
        ? "User reviewed"
        : asset.editable && asset.state === "editable"
          ? "Editable copy made"
          : imageClassificationLabel(asset.classification, target));
  return reason === displayLabels[display] ? "" : reason;
}
/** What discovery found, beside a heading that shows the image's state and,
 * when `reasonShown`, its reason: led by the image's class unless that
 * heading already names it. */
export function imageDiscovery(
  asset: ImageAsset,
  listed: boolean,
  target: string,
  reasonShown: boolean,
) {
  const label =
    imageClassificationLabel(asset.classification, target) ||
    asset.classification;
  const named =
    label === displayLabels[imageDisplay(asset, listed)] ||
    (reasonShown && label === imageReason(asset, listed, target));
  return named ? asset.reason : `${label} · ${asset.reason}`;
}
/** An image's state in the shared words, then its reason. */
export function imageStatus(
  asset: ImageAsset,
  listed: boolean,
  target: string,
) {
  const state = displayLabels[imageDisplay(asset, listed)];
  const reason = imageReason(asset, listed, target);
  return reason ? `${state} · ${reason}` : state;
}

export interface FolderRow {
  /** The folder's path from the image root, as the grid filters by it. */
  path: string;
  name: string;
  /** How far it sits under the folders the list starts from. */
  depth: number;
  /** Its images and its subfolders', as choosing it lists them. */
  count: number;
}

const segments = (path: string) => path.split("/");
/** Folder paths in tree order: each folder before its subfolders, by name. */
const treeOrder = (a: string, b: string) => {
  const left = segments(a);
  const right = segments(b);
  for (let index = 0; index < Math.min(left.length, right.length); index++) {
    const order = left[index].localeCompare(right[index], undefined, {
      numeric: true,
      sensitivity: "base",
    });
    if (order) return order;
  }
  return left.length - right.length;
};

/**
 * The image folders as an indented tree. Each folder counts its subfolders'
 * images, and folders that every image sits under without images of their
 * own, such as img, are left out, so the list starts where folders differ.
 */
export function folderTree(
  folders: readonly { path: string; count: number }[],
): FolderRow[] {
  const counts = new Map<string, number>();
  for (const { path, count } of folders) {
    const parts = path === "." ? ["."] : segments(path);
    for (let end = 1; end <= parts.length; end++) {
      const key = parts.slice(0, end).join("/");
      counts.set(key, (counts.get(key) || 0) + count);
    }
  }
  const direct = new Set(folders.map((folder) => folder.path));
  const children = (parent: string) =>
    [...counts.keys()].filter((path) =>
      parent
        ? path.startsWith(parent + "/") &&
          !path.slice(parent.length + 1).includes("/")
        : path !== "." && !path.includes("/"),
    );
  let shared = "";
  if (!direct.has(".")) {
    for (;;) {
      const next = children(shared);
      if (next.length !== 1 || direct.has(next[0])) break;
      shared = next[0];
    }
  }
  const base = shared ? segments(shared).length : 0;
  return [...counts]
    .filter(
      ([path]) => path === "." || !shared || path.startsWith(shared + "/"),
    )
    .sort(([a], [b]) => (a === "." ? -1 : b === "." ? 1 : treeOrder(a, b)))
    .map(([path, count]) => ({
      path,
      name: path === "." ? "Root images" : segments(path).at(-1)!,
      depth: path === "." ? 0 : segments(path).length - base - 1,
      count,
    }));
}
