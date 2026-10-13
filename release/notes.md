<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Context:** when a game shows script, plugin command or comment text that DazedTL has no pattern for, the **Event text sources** investigation now writes a pattern for that game and turns it on, instead of leaving that text untranslated. **Source choices** lists the patterns written for the game.

### Fixed

- **Translate:** while a Batch waits for the clarification of refused requests, files whose results already arrived read **Working** instead of **Needs review**, also after a restart, and the footer says what the run waits for. Run history no longer reads **At provider** while those results are being saved.
