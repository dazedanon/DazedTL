/**
 * A connection's models searched by what was typed, which doubles as a model
 * ID the list lacks: the models whose ID holds it, and that ID, offered as
 * Use “…”, when no listed model is exactly it.
 */
export function searchModels(models: readonly string[], query: string) {
  const typed = query.trim();
  const search = typed.toLocaleLowerCase();
  return {
    typed,
    matches: models.filter((item) => item.toLocaleLowerCase().includes(search)),
    /** The typed model ID the list lacks, or empty. */
    custom: typed && !models.includes(typed) ? typed : "",
  };
}

/** The choice that takes a typed model ID the list lacks. */
export const typedChoice = (typed: string) => `Use “${typed}”`;

/** What a connection with no model list yet says, and how to get one;
 * `where` names Settings outside it. */
export const noModelList = (connection: string, where = "") =>
  `No model list for ${connection} yet. Check the connection${where} to load one, or enter a model ID.`;
