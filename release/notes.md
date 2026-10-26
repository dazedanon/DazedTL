<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Playtest tools:** a published patch of a game with Forge installed no longer stops players' game at start with "Failed to load" for the Forge plugin: installing Forge now saves its plugin file in the game's checkpoint with plugins.js, and a game already missing it gets it in DazedTL's next change to the game.
- **Translate:** a Chinese translation of a WOLF, KiriKiri or other game outside RPG Maker now wraps to its line width between characters, by the Chinese and Japanese line-break rules, instead of running past the window as one long line.
- **Images:** Chinese or Japanese text drawn into an image no longer shows as boxes when the chosen font lacks its letters: it is drawn in a Chinese or Japanese font the computer has.
- **Translate:** NScripter, KiriKiri and WOLF games no longer lose accented letters such as the ñ of "Señor": they are written without the accent, and a file holding a letter the game's Japanese text encoding can't write at all stops with a message naming the line instead of saving it with the letter missing.
