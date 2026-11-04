<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Context:** Guided's **Guidance** now has the **Assistant notes** tab too, so you can read and edit what your assistant keeps about the game in `AGENTS.md`.

### Fixed

- **GameUpdate:** an update that fails partway, such as on a file the running game holds, a full disk or a folder too deep for Windows ("Could not find a part of the path"), now puts the game back as it was instead of leaving it half patched; a game gets this with its next copy of GameUpdate, such as from **Recreate GameUpdate files**.
- **Text QA:** a speaker fix that named the character in Japanese no longer stops **Apply corrections** with "QA regression failed; all game-file changes were rolled back"; your assistant now writes the name as the game shows it, and a failed apply names the correction that stopped it.
