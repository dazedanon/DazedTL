<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Projects:** a game moved or renamed after estimating keeps its Guided and whole-game cost estimates, and preparing Text QA again goes on with the task in review, whose instructions name the game's new folder.
- **Translate:** a model's refusal written as prose, such as "I won't produce this content, even in translation." or "Send another batch and I'll continue.", or as a bare "Declined.", is no longer accepted as dialogue, and Lines counts lines an earlier run saved that way as left, so the next Translate sends them again. Text QA no longer applies a correction that reads as a refusal.
- **Translate:** opening a big game's translation workspace no longer holds the whole app for seconds while it counts every file's lines and reads its event files; files still being counted read **Counting…**, and the counts are kept across restarts.
