<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **GameUpdate:** on Linux without Git, when the patch site refuses GameUpdate's usual download, it says how to install Git again instead of stopping with "git: command not found", which 2.59.3 brought.
- **GameUpdate:** on Windows, a patch too deep for the game's folder now stops before copying anything and asks to move the game to a shorter folder, instead of leaving it half patched; a patch whose Git LFS files a site's download leaves out is refused too.
- **GameUpdate:** messages no longer show internal tags such as PATCH_ERR and name the Git step that failed, a second GameUpdate window no longer deletes the first one's download, and closing the Linux terminal no longer leaves a copy of the script behind.
