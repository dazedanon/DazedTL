<!-- The next release's notes; see docs/development.md#release-notes. -->
### Fixed

- **Translate:** a Batch rerun that finds nothing new to send for a file no longer reads it Ready to apply, or counts the task done, when the file's earlier translation is not in the game yet; the file keeps the state the earlier run left.
