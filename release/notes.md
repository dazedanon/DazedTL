<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Context:** Guided's **Guidance** now has the **Assistant notes** tab too, so you can read and edit what your assistant keeps about the game in `AGENTS.md`.

### Fixed

- **Context:** the **Assistant notes** (`AGENTS.md`) are no longer deleted by a game update when the game had them before Set up, are no longer saved with the files of new Assistant-led checkpoints, so undoing an older one no longer waits on a later one or brings back older notes, and an older Guided draft no longer replaces them: Save says how to keep either; one another program holds no longer fails every change to the game, and on Windows an `agents.md` in another case no longer reaches players' downloads.
- **GameUpdate:** an update that fails partway, such as on a file the running game holds, a full disk or a folder too deep for Windows ("Could not find a part of the path"), now puts the game back as it was instead of leaving it half patched; a game gets this with its next copy of GameUpdate, such as from **Recreate GameUpdate files**.
- **Text QA:** reviews no longer propose a speaker fix that names the character in Japanese, which stopped **Apply corrections** with "QA regression failed; all game-file changes were rolled back"; a failed apply now names the correction that stopped it.
