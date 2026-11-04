import type {
  Document,
  DocumentDraft,
  DocumentDrafts,
  Documents,
  DocumentsSaved,
} from "../api/contracts";

/** The work an unsaved draft can hold up, as each document's definition
 * names it: handing a task to an assistant, or the work that reads what
 * translation requests carry. */
export type HeldWork = Document["holdsUp"][number];

/** Where a document stands in its editor, the same in every method. */
export function documentStatus(
  document: Document | undefined,
  draft: DocumentDraft | undefined,
) {
  if (document?.state === "unreadable") return "unreadable";
  // The backend decides, as its save refuses, whether the file changed on
  // disk since the draft began.
  if (draft && document?.changed) return "changed";
  if (draft) return "draft";
  return document?.state === "saved" ? "saved" : "missing";
}

/** The documents in the editors' order, the backend's, then any draft of
 * one no longer listed. */
export function documentNames(documents: Documents, drafts: DocumentDrafts) {
  return [...new Set([...Object.keys(documents), ...Object.keys(drafts)])];
}

/** The drafts that hold up `work`; one whose document is unknown holds up
 * every kind. */
export function heldDrafts(
  documents: Documents,
  drafts: DocumentDrafts,
  work: HeldWork,
) {
  return Object.keys(drafts).filter(
    (name) => documents[name]?.holdsUp.includes(work) ?? true,
  );
}

/**
 * Why `work` waits, naming the drafts that hold it up and the tab, Context
 * or Guidance, that saves them, as the backend refuses it; empty when none
 * does.
 */
export function draftsRefusal(
  documents: Documents,
  drafts: DocumentDrafts,
  work: HeldWork,
  tab: "Context" | "Guidance",
) {
  const held = heldDrafts(documents, drafts, work);
  if (!held.length) return "";
  const titles = held.map((name) => documents[name]?.title).filter(Boolean);
  return `Save or discard your ${titles.join(", ") || "guidance"} ${held.length === 1 ? "draft" : "drafts"} in ${tab} first.`;
}

/**
 * The documents a save of `names` leaves out because DazedTL can't read
 * their file: those with a draft among them and, for a save of the whole
 * set, every core document Guidance still needs.
 */
export function unreadableLeftOut(
  documents: Documents,
  drafts: DocumentDrafts,
  names: string[],
  whole: boolean,
) {
  return Object.keys(documents).filter(
    (name) =>
      documents[name].state === "unreadable" &&
      ((names.includes(name) && !!drafts[name]) ||
        (whole && documents[name].kind === "core")),
  );
}

/** What a save of guidance did, named for the tab that saves it, and the
 * files it left out because DazedTL can't read them. */
export function savedMessage(
  label: "Context" | "Guidance",
  result: DocumentsSaved | null,
  discarded: string[],
  unreadable: string[],
  documents: Documents,
) {
  const done = result?.saved.length
    ? `${label} saved.`
    : discarded.length
      ? discarded.length === 1
        ? "Draft discarded."
        : "Drafts discarded."
      : unreadable.length
        ? ""
        : label === "Guidance"
          ? "Guidance is already saved."
          : "Nothing to save.";
  if (!unreadable.length) return done;
  const files = unreadable.map((name) => documents[name].file).join(", ");
  const why =
    unreadable.length === 1 ? "its tab says why" : "their tabs say why";
  return `${done} DazedTL can't read ${files}; ${why}.`.trim();
}
