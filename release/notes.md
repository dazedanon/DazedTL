<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** after stopping a Live run that translated several files at once (**Concurrent files** above 1 in settings carried over from an earlier version), every finished file counts as saved. Some used to read as not saved and were translated again.
- **Plugin files:** games whose plugin list repeats a plugin, such as an empty divider plugin listed many times, no longer stop **Copy plugin task** with "Duplicate configured plugins need investigation before exact scope can be formed."
