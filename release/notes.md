<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Context:** after **Save context** failed while the game's version history was locked, every later save said "This guidance changed on disk" with no way past it but discarding the draft; the draft now saves once the lock is gone, including after a restart.
