<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Assistant-led:** Options chooses which tools your assistant installs in the game: GameUpdate and Forge, both on by default, and TL Inspector, off by default; Forge and TL Inspector are for MV and MZ games. A patch waits until the game has the tools you chose.

### Changed

- **Assistant-led:** the page opens on Options, now the first tab, until your assistant starts, and each option says what it does under its name.
- **Settings:** the Credits tab is one shorter list that names each person once, with V2 marking work on DazedTL and V1 work on DazedMTLTool, the tool it grew from.

### Removed

- **Translate:** the engine modules DazedTL carried over from DazedMTLTool that no screen runs any more are gone, such as CSV, TyranoScript, Kirikiri, JSON, WOLF RPG, Ren'Py, Unity and SRPG Studio; Guided Translate keeps RPG Maker MV, MZ and VX Ace and image text. A run the old engine picker saved for one of them now says that engine was retired and sends nothing, instead of resuming.

### Fixed

- **Translate:** a Gemini Batch sent before 2.52.4 on a Custom Gemini-compatible connection, whose replies held refusals, no longer stops at "Reconcile the clarification Batch submission."; its refused lines are asked again at Google, where that Batch was sent, with the same connection's key.
- **Translate:** a request that fails inside an Anthropic Batch now shows Anthropic's own error message in **Inspect run** and in the file's error, instead of program text.
- **Translate:** a Guided Batch with no successful replies whose records could not be read now fails once, instead of failing again a moment later.
