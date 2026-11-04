<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Compare:** a new page in the sidebar translates a few lines of your game with up to four models side by side, from any of your connections, or one model with a changed thinking effort, glossary or instruction, sent as a real run sends them, so you can pick a model in equal conditions; **Blind** hides the names until you've picked the best line of each.
- **Context:** Guided's **Guidance** now has the **Assistant notes** tab too, so you can read and edit what your assistant keeps about the game in `AGENTS.md`.

### Fixed

- **GameUpdate:** an update that fails partway, such as on a file the running game holds, a full disk or a folder too deep for Windows ("Could not find a part of the path"), now puts the game back as it was instead of leaving it half patched; a game gets this with its next copy of GameUpdate, such as from **Recreate GameUpdate files**.
- **Text QA:** reviews no longer propose a speaker fix that names the character in Japanese, which stopped **Apply corrections** with "QA regression failed; all game-file changes were rolled back"; a failed apply now names the correction that stopped it.
