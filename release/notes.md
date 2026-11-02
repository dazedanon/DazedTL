<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Assistant-led:** Options chooses which tools your assistant installs in the game: GameUpdate and Forge, both on by default, and TL Inspector, off by default; Forge and TL Inspector are for MV and MZ games. A patch waits until the game has the tools you chose.

### Changed

- **Assistant-led:** the page opens on Options, now the first tab, until your assistant starts, and each option says what it does under its name.
- **Settings:** the Credits tab is one shorter list that names each person once, with V2 marking work on DazedTL and V1 work on DazedMTLTool, the tool it grew from.

### Fixed

- **Translate:** a Gemini Batch sent before 2.52.4 on a Custom Gemini-compatible connection, whose replies held refusals, no longer stops at "Reconcile the clarification Batch submission."; its refused lines are asked again at Google, where that Batch was sent, with the same connection's key.
