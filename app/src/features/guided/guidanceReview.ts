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
