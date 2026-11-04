<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **GameUpdate:** an update that fails partway, such as on a file the running game holds, a full disk or a folder too deep for Windows ("Could not find a part of the path"), now puts the game back as it was instead of leaving it half patched; a game gets this with its next copy of GameUpdate, such as from **Recreate GameUpdate files**.
