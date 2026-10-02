import type { ContextSetup, Documents } from "../../api/contracts";

export const coreGuidance = ["glossary", "quirks", "game"];
export const guidanceTitle = (name: string) => ({ glossary: "Glossary", quirks: "Style & quirks", game: "Game context" })[name] || name.replace("custom:", "Skill: ");

export function guidanceNames(documents: Documents, drafts: Documents) {
  return [...coreGuidance, ...[...new Set([...Object.keys(documents), ...Object.keys(drafts)])].filter((name) => name.startsWith("custom:"))];
}

export function guidanceStatus(name: string, documents: Documents, drafts: Documents, setup: ContextSetup) {
  const saved = documents[name], draft = drafts[name], status = setup.documents[name];
  if (draft && draft.revision !== saved?.revision) return "Conflict";
  if (!(draft || saved)?.text.trim()) {
    if (status?.intentionalEmpty && !draft) return "Intentionally empty";
    return status?.exists ? "Empty" : "Missing";
  }
  if (draft) return "Draft";
  if (status?.needsReview) return "Needs review";
  return "Saved";
}

export function guidanceBlockers(names: string[], documents: Documents, drafts: Documents, setup: ContextSetup) {
  return names.filter((name) => ["Conflict", "Missing", "Empty"].includes(guidanceStatus(name, documents, drafts, setup)));
}

/** Report successful document writes if a later save or revision review fails. */
export async function saveGuidanceSet(names: string[], save: (name: string) => Promise<Documents>, review: (name: string, saved: Documents) => Promise<unknown>) {
  const savedNames: string[] = [];
  for (const name of names) {
    try {
      const saved = await save(name);
      if (saved[name]) savedNames.push(name);
      await review(name, saved);
    } catch (error) {
      if (!savedNames.length) throw error;
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`Saved ${savedNames.map(guidanceTitle).join(", ")}. ${message} Remaining drafts are retained.`, { cause: error });
    }
  }
}
