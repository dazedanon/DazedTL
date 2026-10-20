<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Maps & events:** in a project translated before **Comment text** came on, a file whose choice help is still in Japanese now reads **Needs review** and counts those lines as untranslated, instead of looking finished; **Translate** sends only the help.
- **Maps & events:** when several maps repeat the same scene, a Batch still sends it once, and now each of those maps counts its lines and shows which request failed validation, instead of "validation mismatches were recorded, but this older run did not retain which request failed".
- **Text QA:** updating DazedTL no longer makes finished QA read Outdated with "An update changed QA's rules after this task was prepared", so its corrections apply, Undo and Apply again keep working, and QA in progress, including QA started with 2.23.0 to 2.24.0, goes on where it stopped instead of reviewing again.
- **Maps & events:** translated choice help now keeps the game's own event commands and its own help rows, so translating it again no longer deletes or fills rows such as "(1/3)" or a blank spacer, and saved games stay at their place in the event.
- **Maps & events:** choice help shown beside a portrait now wraps to the portrait's width as it is translated, and its list items keep a row each.
- **Maps & events:** choice help markers listed by a plugin are now found in a plugin list without a semicolon or with code after it, by translation and Text QA alike.
- **Assistant-led:** choice help the assistant translates is now fitted to the game's Line widths like its other text.
- **Text QA:** the playtest now matches an untranslated message it sees with the line it lists as never translated, and a message whose speaker name alone was translated counts as never translated.
