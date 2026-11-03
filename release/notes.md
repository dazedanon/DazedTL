<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **GameUpdate:** a game gets GameUpdate's Git download from 2.59.2, and the fixes below, only after you choose **Recreate GameUpdate files** (Guided) or your assistant prepares the game again (Assistant-led), then push the translation; until then its players run the GameUpdate it shipped with.

### Fixed

- **GameUpdate:** when the patch site refuses its usual download, GameUpdate now says the repository is missing, private or unreachable instead of downloading Git for nothing and asking for a username, and refuses a patch kept in Git LFS instead of copying placeholder files into the game.
- **GameUpdate:** on Windows, patches with deep folders no longer fail to unpack, a copy of Git for Windows that a virus scanner held or damaged is replaced by itself, and two GameUpdate windows on one game no longer clash.
- **GameUpdate:** on SteamOS, the message for a missing Git now gives commands that work on its read-only system.
