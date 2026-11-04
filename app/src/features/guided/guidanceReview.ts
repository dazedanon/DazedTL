import type { ContextSetup, Documents } from "../../api/contracts";

export const coreGuidance = ["glossary", "quirks", "game"];
/** AGENTS.md at the game's root: every assistant task reads and keeps it,
 * and no translation request carries it. */
export const assistantNotes = "notes";
export const guidanceTitle = (name: string) =>
  ({
    glossary: "Glossary",
    quirks: "Style & quirks",
    game: "Game context",
    notes: "Assistant notes",
  })[name] || name.replace("custom:", "Skill: ");

/** The documents the Guidance task shows and Save guidance sends: the core
 * guidance, the assistant notes, then the custom skills. Notes the game's
 * AGENTS.md can't be read into stay out, a draft of them too, so they never
 * block saving the rest. */
export function guidanceNames(documents: Documents, drafts: Documents) {
  return [
    ...coreGuidance,
    ...(assistantNotes in documents ? [assistantNotes] : []),
    ...[...new Set([...Object.keys(documents), ...Object.keys(drafts)])].filter(
      (name) => name.startsWith("custom:"),
    ),
  ];
}

/** Whether Guidance holds edits Save guidance would send, which estimates
 * and runs wait for; a draft it leaves out never holds them up. */
export function guidanceEdited(documents: Documents, drafts: Documents) {
  return guidanceNames(documents, drafts).some((name) => !!drafts[name]);
}

export function guidanceAvailability(documents: ContextSetup["documents"]) {
  const missing = coreGuidance.filter((name) => !documents[name]?.exists);
  return { complete: !missing.length, missing };
}
