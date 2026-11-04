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
 * guidance, the assistant notes unless the game's can't be read, then the
 * custom skills. */
export function guidanceNames(documents: Documents, drafts: Documents) {
  const names = new Set([...Object.keys(documents), ...Object.keys(drafts)]);
  return [
    ...coreGuidance,
    ...(names.has(assistantNotes) ? [assistantNotes] : []),
    ...[...names].filter((name) => name.startsWith("custom:")),
  ];
}

export function guidanceAvailability(documents: ContextSetup["documents"]) {
  const missing = coreGuidance.filter((name) => !documents[name]?.exists);
  return { complete: !missing.length, missing };
}
