<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Context:** after **Save context** failed while the game's version history was locked, every later save said "This guidance changed on disk" with no way past it but discarding the draft; the draft now saves once the lock is gone, including after a restart.
- **Context:** the first **Save context** on a game whose version history was not set up yet could freeze the whole app for minutes on a big game, and closing it said saving was taking longer than expected; it now saves at once.
