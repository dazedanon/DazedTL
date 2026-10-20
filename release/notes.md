<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Database files and Maps & events:** **Lines** and each file's status now come from the file itself, so they show before the first run (such as 0 / 240), stay right after reruns and **Reload from game**, and a task reads done only when no Japanese is left; hover a **Needs review** status to see why, and click a file's eye to list its lines left.

### Fixed

- **Maps & events:** a message or scrolling text the translation leaves untranslated or declines now keeps every row as the game has it, instead of being joined into one row, so its event keeps its place for saved games.
- **VX Ace:** translations now show in the game right after **Apply**, as do Plugin files, Text QA, Line widths and restores in History, instead of waiting for a separate packing step; a game that came with `ace_json` already converted and `Game.rgss3a` still beside `Game.exe` now has Set up set the archive aside, keeping its translations, instead of releasing the untranslated game.
- **Maps & events:** in a project translated before **Comment text** came on, choice help still in Japanese now counts as lines left instead of the file looking finished; **Translate** sends only the help.
- **Database files and Maps & events:** after a rerun that sent only some lines, such as choice help, **Lines** and the project's lines translated no longer drop to that rerun's own lines (for example 2 / 2 instead of 11 / 11).
- **Maps & events:** when several maps repeat the same scene, a Batch still sends it once, and now each of those maps counts its lines and shows which request failed validation, instead of "validation mismatches were recorded, but this older run did not retain which request failed".
- **Text QA:** updating DazedTL no longer makes finished QA read Outdated with "An update changed QA's rules after this task was prepared", so its corrections apply, Undo and Apply again keep working, and QA in progress, including QA started with 2.23.0 to 2.24.0, goes on where it stopped instead of reviewing again.
- **Maps & events:** translated choice help now keeps the game's own event commands and its own help rows, so translating it again no longer deletes or fills rows such as "(1/3)" or a blank spacer, and saved games stay at their place in the event.
- **Maps & events:** choice help shown beside a portrait now wraps to the portrait's width as it is translated, and its list items keep a row each.
- **Maps & events:** choice help markers listed by a plugin are now found in a plugin list without a semicolon or with code after it, by translation and Text QA alike.
- **Assistant-led:** choice help the assistant translates is now fitted to the game's Line widths like its other text.
- **Text QA:** the playtest now matches an untranslated message it sees with the line it lists as never translated, and a message whose speaker name alone was translated counts as never translated.
- **Text QA:** an applied correction now colors only the words it changed, instead of the whole new line, so an unchanged second row no longer looks changed.
- **Playtest:** a placeholder glyph such as ◯ that the message window draws is now reported once per message, instead of once for the whole run.
