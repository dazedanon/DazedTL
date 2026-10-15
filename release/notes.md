<!-- The next release's notes; see docs/development.md#release-notes. -->
### Fixed

- **Translate:** translating an RPG Maker MV/MZ or SRPG Studio game's database again after a game update no longer replaces the game glossary's database sections, such as Items, Skills and Weapons, with only the names it just translated; the other rows stay, and a name translated again takes its new translation.
- **Translate:** adding translated names to a glossary section no longer drops a row that has a note after its translation, such as a character's voice notes in Game Characters.
