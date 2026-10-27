<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Assistant-led:** **Copy post-update task** now has your assistant finish a game update the way it translated the game, in the project's mode and languages: it keeps the translations of lines the update left alone, waits for you to approve API costs on **Progress**, and runs QA, the playtest and the patch again, instead of editing the game's files by hand and translating everything itself, and copying it works after any finished update.
- **Versions:** A game with more than 100 checkpoints since its last version or update, such as after a long Assistant-led run, keeps its version, so Guided translation runs no longer refuse to start and ask you to set up the original and translation branches again.
