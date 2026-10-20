<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Maps & events:** in a project translated before **Comment text** came on, a file whose choice help is still in Japanese now reads **Needs review** and counts those lines as untranslated, instead of looking finished; **Translate** sends only the help.
- **Maps & events:** when several maps repeat the same scene, a Batch still sends it once, and now each of those maps counts its lines and shows which request failed validation, instead of "validation mismatches were recorded, but this older run did not retain which request failed".
- **Text QA:** updating DazedTL no longer makes finished QA read Outdated with "An update changed QA's rules after this task was prepared", so its corrections apply, Undo and Apply again keep working, and QA in progress, including QA started with 2.23.0 to 2.24.0, goes on where it stopped instead of reviewing again.
