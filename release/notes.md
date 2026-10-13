<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **App:** a game with a long translation history stays responsive. Every screen update checked each saved run's files again, rereading all of them once the history passed about 20,000 files, so clicks, page switches and estimates waited seconds on Windows. The checks now reuse what they read before.
