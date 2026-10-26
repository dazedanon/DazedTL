/** The layout the engine reads from each guidance file, shown while it is
 * empty, for a game whose text is in *source*: each entry names the source
 * term, then its translation. */
export function guidanceFormats(source: string): Record<string, string> {
  return source === "Japanese"
    ? {
        glossary:
          "# Game Characters\nアリス (Alice) - Female. The heroine; polite, formal speech.\n\n# Terms\n魔導書 (Grimoire)",
        quirks:
          "- Battle log and system messages stay in the third person.\n- ゴンベエ's ござる endings read as archaic samurai speech.",
        game: "世界観 (Theme / setting) - \n時代感 (Era / technology level) - \n文体方針 (Register policy) - \n固有名詞方針 (Naming policy) - ",
      }
    : {
        glossary:
          "# Game Characters\nAlice (アリス) - Female. The heroine; polite, formal speech.\n\n# Terms\nGrimoire (魔導書)",
        quirks:
          "- Battle log and system messages stay in the third person.\n- Gonbei's old-fashioned speech reads as an archaic samurai's.",
        game: "Theme / setting - \nEra / technology level - \nRegister policy - \nNaming policy - ",
      };
}
