<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Releases:** each new version is also published as a GitHub Release with its notes, so the GitHub page shows the latest version and what changed.

### Changed

- **User guide:** a third of its old length, each step in a few lines: what to click, what to paste into your assistant and what comes next.
- **GitHub page:** the README shows DazedTL at work: a game translated from Japanese to English, a live translation, handing tasks to your assistant, Text QA's corrections and what a game typically costs, with links to the Discord and to support DazedTL.

### Fixed

- **Plugin files:** a plugin's quest subject, map names and drawn labels are translated in their own text only, so other settings and code on the same line of plugins.js are no longer sent or overwritten, and 回 in a word such as 回復 is no longer written as x.
