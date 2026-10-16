/** What the Glossary check task shows, from its summary and its lines. */

import type {
  GlossaryLine,
  GlossaryState,
  GlossaryTerm,
} from "../../api/contracts";

/**
 * Where the check stands: never run, read from text that has changed since,
 * lines waiting for a choice or a fix to apply, or done.
 */
export function glossaryPhase(state: GlossaryState) {
  if (!state.scan) return "none";
  if (!state.current) return "outdated";
  return state.open || state.fixes ? "review" : "done";
}

export type GlossaryGroup = {
  key: string;
  /** The terms each of its lines lacks, in the order the Japanese has them. */
  terms: GlossaryTerm[];
  lines: GlossaryLine[];
};

/** The terms a line lacks, in the order its Japanese holds them. */
const ordered = (line: GlossaryLine) =>
  [...line.terms].sort((a, b) => a.start - b.start);

/** Lines grouped by the terms they lack, larger groups first. */
export function byTerms(lines: GlossaryLine[]) {
  const groups = new Map<string, GlossaryGroup>();
  for (const line of lines) {
    const terms = ordered(line);
    const key = terms.map((term) => term.source).join("\u0000");
    const group = groups.get(key) || { key, terms, lines: [] };
    group.lines.push(line);
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => b.lines.length - a.lines.length);
}

/**
 * The lines to decide, grouped by the terms they lack, and the lines kept
 * earlier. Groups with a proposal come first, since those are most often a
 * term the translation renders another way; the rest are often an ordinary
 * word written like the term. A line kept on this visit stays where it was,
 * so the list does not move under the pointer.
 */
export function glossaryGroups(
  found: GlossaryLine[],
  keptHere: ReadonlySet<string>,
) {
  const earlier = (line: GlossaryLine) =>
    line.state === "kept" && !keptHere.has(line.key);
  const all = byTerms(found.filter((line) => !earlier(line)));
  const proposed = all.filter((group) =>
    group.lines.some((line) => line.proposal),
  );
  return {
    proposed,
    unproposed: all.filter((group) => !proposed.includes(group)),
    kept: found.filter(earlier),
  };
}
