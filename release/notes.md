<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Database files and Maps & events:** **Lines** and each file's status now come from the file itself, so they show before the first run (such as 0 / 240), stay right after reruns and **Reload from game**, and a task reads done only when no Japanese is left; hover a **Needs review** status to see why, and click a file's eye to list its lines left.

### Fixed

- **VX Ace:** translations now show in the game right after **Apply**, as do Plugin files, Text QA, Line widths and restores in History, instead of waiting for a separate packing step; a game that came with `ace_json` already converted and `Game.rgss3a` still beside `Game.exe` now has Set up set the archive aside, keeping its translations, instead of releasing the untranslated game.
- **Maps & events:** in a project translated before **Comment text** came on, choice help still in Japanese now counts as lines left instead of the file looking finished; **Translate** sends only the help.
- **Database files and Maps & events:** after a rerun that sent only some lines, such as choice help, **Lines** and the project's lines translated no longer drop to that rerun's own lines (for example 2 / 2 instead of 11 / 11).
- **Maps & events:** when several maps repeat the same scene, a Batch still sends it once, and now each of those maps counts its lines and shows which request failed validation, instead of "validation mismatches were recorded, but this older run did not retain which request failed".
- **Text QA:** updating DazedTL no longer makes finished QA read Outdated with "An update changed QA's rules after this task was prepared", so its corrections apply, Undo and Apply again keep working, and QA in progress, including QA started with 2.23.0 to 2.24.0, goes on where it stopped instead of reviewing again.
