import type { Documents } from "../api/contracts.ts";

/** A comparison authorizes rebasing only onto the saved version the user saw. */
export function resolveDocumentDraft(drafts: Documents, name: string, saved: Documents[string], reviewedRevision: string, choice: "saved" | "draft"): Documents {
  if (saved.revision !== reviewedRevision) throw new Error("Saved guidance changed again. Review the new version before resolving it.");
  const result = { ...drafts };
  if (choice === "saved") delete result[name];
  else {
    if (!result[name]) throw new Error("The draft is no longer available. Reload the saved guidance.");
    result[name] = { ...result[name], revision: saved.revision };
  }
  return result;
}
