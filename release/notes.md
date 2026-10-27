<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Assistant-led:** on games that keep their images in archives, such as WOLF RPG Editor games, your assistant now translates them through DazedTL's **Images** steps on the folder it unpacks them into, with the same image checks and **Progress** counts as other games, then packs them back into the game.

### Fixed

- **Assistant-led:** **Copy post-update task** now has your assistant finish a game update the way it translated the game, in the project's mode and languages: it keeps the translations of lines the update left alone, waits for you to approve API costs on **Progress**, and runs QA, the playtest and the patch again, instead of editing the game's files by hand and translating everything itself, and copying it works after any finished update.
