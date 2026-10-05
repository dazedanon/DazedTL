import type { ContextSetup, Documents } from "../../api/contracts";

export const coreGuidance = ["glossary", "quirks", "game"];
export const guidanceTitle = (name: string) =>
  ({ glossary: "Glossary", quirks: "Style & quirks", game: "Game context" })[
    name
  ] || name.replace("custom:", "Skill: ");

export function guidanceNames(documents: Documents, drafts: Documents) {
  return [
    ...coreGuidance,
    ...[...new Set([...Object.keys(documents), ...Object.keys(drafts)])].filter(
      (name) => name.startsWith("custom:"),
    ),
  ];
}

export function guidanceAvailability(documents: ContextSetup["documents"]) {
  const missing = coreGuidance.filter((name) => !documents[name]?.exists);
  return { complete: !missing.length, missing };
}

/** Report successful document writes if a later save fails. */
export async function saveGuidanceSet(
  names: string[],
  save: (name: string) => Promise<Documents>,
) {
  const savedNames: string[] = [];
  for (const name of names) {
    try {
      const saved = await save(name);
      if (saved[name]) savedNames.push(name);
    } catch (error) {
      if (!savedNames.length) throw error;
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(
        `Saved ${savedNames.map(guidanceTitle).join(", ")}. ${message} Remaining drafts are retained.`,
        { cause: error },
      );
    }
  }
}
