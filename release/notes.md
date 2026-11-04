<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Context:** Guided's **Guidance** now has the **Assistant notes** tab too, so you can read and edit what your assistant keeps about the game in `AGENTS.md`.

### Fixed

- **Database:** the currency unit after an amount of money, such as 円, and the variable names a plugin draws, such as LL_VariableWindow's label, are now translated in Guided and Assistant-led alike; other variable names stay as they are, since plugins and scripts may look a variable up by its name.
  An already translated game shows them as lines left in System.json until its next Database run.
- **GameUpdate:** an update that fails partway, such as on a file the running game holds, a full disk or a folder too deep for Windows ("Could not find a part of the path"), now puts the game back as it was instead of leaving it half patched; a game gets this with its next copy of GameUpdate, such as from **Recreate GameUpdate files**.
- **Text QA:** reviews no longer propose a speaker fix that names the character in Japanese, which stopped **Apply corrections** with "QA regression failed; all game-file changes were rolled back"; a failed apply now names the correction that stopped it.
