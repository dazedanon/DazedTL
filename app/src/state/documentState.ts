import type {
  Document,
  DocumentDraft,
  DocumentDrafts,
  Documents,
} from "../api/contracts";

/** The work an unsaved draft can hold up, as each document's definition
 * names it: handing a task to an assistant, or the work that reads what
 * translation requests carry. */
export type HeldWork = Document["holdsUp"][number];

/**
 * Whether a document's file changed on disk since its draft began, as an
 * assistant changes it: the draft began from another revision, or from no
 * file, and the file doesn't already hold the draft's text.
 */
export function changedOnDisk(document: Document, draft: DocumentDraft) {
  const began =
    draft.revision === ""
      ? document.state === "missing"
      : draft.revision === document.revision;
  return !began && draft.text !== document.text;
}

/** Where a document stands in its editor, the same in every method. */
export function documentStatus(
  document: Document | undefined,
  draft: DocumentDraft | undefined,
) {
  if (document?.state === "unreadable") return "unreadable";
  if (draft && document && changedOnDisk(document, draft)) return "changed";
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
