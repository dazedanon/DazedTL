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
};

/** "Japanese to English". */
export const pairLabel = (languages: GameLanguages) =>
  `${languages.source} to ${languages.target}`;

// BCP 47 tags of the languages games are written in or translated into
// most, by name; any other name leaves the page's language.
const TAGS: Record<string, string> = {
  arabic: "ar",
  chinese: "zh",
  english: "en",
  french: "fr",
  german: "de",
  indonesian: "id",
  italian: "it",
  japanese: "ja",
  korean: "ko",
  polish: "pl",
  portuguese: "pt",
  russian: "ru",
  spanish: "es",
  thai: "th",
  turkish: "tr",
  ukrainian: "uk",
  vietnamese: "vi",
};

/** The `lang` attribute of text in a language, so the system draws it in
 * that language's forms, such as Japanese kanji over Chinese ones. */
export function languageTag(name: string): string | undefined {
  return TAGS[name.trim().toLowerCase()];
}
