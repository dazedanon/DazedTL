<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Checkpoints:** each change DazedTL saves to a game starts half as many Git processes once DazedTL has saved one, and the Checkpoints tab, undo and go back start far fewer, so they finish sooner on Windows, where each process can take a tenth of a second.
