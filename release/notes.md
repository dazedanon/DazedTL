<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Database files and Maps & events:** **Lines** and each file's status now come from the file itself, so they show before the first run (such as 0 / 240), stay right after reruns and **Reload from game**, and a task reads done only when no Japanese is left; hover a **Needs review** status to see why, and click a file's eye to list its lines left.

### Fixed

- **Maps & events:** in a project translated before **Comment text** came on, choice help still in Japanese now counts as lines left instead of the file looking finished; **Translate** sends only the help.
- **Database files and Maps & events:** after a rerun that sent only some lines, such as choice help, **Lines** and the project's lines translated no longer drop to that rerun's own lines (for example 2 / 2 instead of 11 / 11).
