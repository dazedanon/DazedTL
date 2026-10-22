<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Checkpoints:** **Copy assets & finish** in the Game updates tool rebuilds a damaged record of a game update's assets from the release folder the update was applied from, as Guided does, and a record it cannot rebuild says to copy the assets yourself or go back to the checkpoint before the update.
- **VX Ace:** applying translated scripts no longer renames a script whose name holds characters such as `<>:"?`, so the editor shows the names you made and a later game update does not read Scripts.rvdata2 as changed.
- **Translate:** a Batch rerun that finds nothing new to send for a file no longer reads it Ready to apply, or counts the task done, when the file's earlier translation is not in the game yet; the file keeps the state the earlier run left.
- **Release:** right after a build, **Done** on the last saved ZIP reports it, instead of "Patch ZIP saved." beside the build button saying it again.
