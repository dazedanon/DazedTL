<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Playtest tools:** a published patch of a game with Forge installed no longer stops players' game at start with "Failed to load" for the Forge plugin: installing Forge now saves its plugin file in the game's checkpoint with plugins.js, and a game already missing it gets it in DazedTL's next change to the game.
- **Translate:** NScripter, KiriKiri and WOLF games no longer lose accented letters such as the ñ of "Señor": they are written without the accent, and a file holding a letter the game's Japanese text encoding can't write at all stops with a message naming the line instead of saving it with the letter missing.
