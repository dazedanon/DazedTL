<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Context:** when a game shows script, plugin command or comment text that DazedTL has no pattern for, the **Event text sources** investigation now writes a pattern for that game and turns it on, instead of leaving that text untranslated. **Source choices** lists the patterns written for the game.

### Removed

- **Windows:** DazedTL no longer includes four unused helper programs that Windows Security and some other antivirus programs reported as a trojan and removed. They were old reference tools that no DazedTL step runs, so nothing changes in how DazedTL works.

### Fixed

- **Translate:** after **Retry saving results**, files saved by an earlier attempt keep their cost and time instead of reading $0.0000 and 0.0s, so the run's total cost is right again.
- **Translate:** a Database Batch no longer fails to save with "No fetched result matches this request" for **States.json** and the files after it. **Retry saving results** now saves a Batch that already failed this way from its existing results, without sending anything again.
- **Translate:** while a Batch waits for the clarification of refused requests, files whose results already arrived read **Working** instead of **Needs review**, also after a restart, and the footer says what the run waits for. Run history no longer reads **At provider** while those results are being saved.
- **Translate:** **Apply** on a large game opens its review in seconds instead of many minutes, so applying no longer fails with "This publication review expired or was already used." Applying itself is faster, **Review restore** after an interrupted Apply also opens in seconds, and each finished Apply no longer keeps a second copy of every file it wrote, about 400 MB on a large game.
