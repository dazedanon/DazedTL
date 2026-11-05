<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Project page:** a translation file lists each message as **Translate** sends it, alike from a translated and an untranslated copy of the game: with **First-line names** on, or a name a message shows on a row of its own, such as 【Name】 or Name：, the name is a line of its own and gives its speech that speaker, and a row opening with a code such as `\SE[1]` starts a line of its own; importing it no longer runs a name into its speech or a code into the row before when **Translate** applies it, text imported before included, no longer empties rows a translation left in Japanese, and keeps no blank row in a line's Japanese; an import skips those messages in a file exported before, or from a project whose **First-line names** setting differs.
- **Assistant-led:** writing the game no longer runs a name on a row of its own, such as one above its speech, into the speech after it.
