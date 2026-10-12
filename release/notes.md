<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Plugin files:** reviewing and applying translated plugins is faster, most of all on Windows: the app checks each unchanged script once instead of again for every file in the review.

### Fixed

- **Plugin files:** a script check that never finishes now stops at its time limit with a message saying so, instead of an internal error.
