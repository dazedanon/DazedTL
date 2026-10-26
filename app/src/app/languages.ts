/** The languages a project translates between, as labels name them for its
 * source and target text (backend/dazedtl/settings/language_pair.py). The
 * open project's come from LanguagesProvider. */
import type { GameLanguages } from "../api/contracts.ts";

/** What a game set up before its languages were recorded translates, and
 * what labels say while a game can't be read. */
export const DEFAULT_LANGUAGES: GameLanguages = {
  source: "Japanese",
  target: "English",
  characters: false,
  sourceTag: "ja",
  targetTag: "en",
};

/** "Japanese to English". */
export const pairLabel = (languages: GameLanguages) =>
  `${languages.source} to ${languages.target}`;
