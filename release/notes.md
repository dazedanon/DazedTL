<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **VX Ace:** once anything was applied, Release builds the patch ZIP again instead of refusing with "Supply unique source and guidance file paths.", and the patch leaves out the `ace_json` folder; a game update keeps your translation instead of putting the new version's Japanese back, and a new version that comes with `Game.rgss3a` is converted as Set up converts the game instead of waiting for an assistant.
- **Translate:** a kaomoji with half-width marks, such as (ﾟдﾟ), no longer comes back with its eyes stacked on the mouth or as a box, and a short line such as え？ that the model gives back untranslated is no longer saved as translated; it keeps its original text and the next Translate sends it again.
