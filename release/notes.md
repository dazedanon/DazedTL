<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Projects:** a game moved or renamed after estimating keeps its Guided and whole-game cost estimates, and preparing Text QA again goes on with the task in review, whose instructions name the game's new folder.
- **Translate:** opening a big game's translation workspace no longer holds the whole app for seconds while it counts every file's lines and reads its event files; files still being counted read **Counting…**, and the counts are kept across restarts.
