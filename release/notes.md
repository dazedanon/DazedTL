<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Assistant-led:** Wolf Pro games that keep their own archive key beside their archives now open and unpack, including archives renamed to .data, .pak and similar.
- **Assistant-led:** the bundled Wolf tools read and rewrite data files protected by Wolf 2.x and Wolf Pro 3.1 to 3.5.

### Fixed

- **Guided:** large games no longer make the app slow to answer; on a 5,000-file game each refresh took 2 to 3 seconds on Windows and every click waited behind it, and now takes under a tenth of a second.
- **Set up:** on large games the Context page opens as soon as Save version finishes, instead of about 20 seconds later on Windows; setting up a 2.5 GB test game on Windows went from about 1.5 minutes to under 1.
- **Project:** Wolf games whose archives sit in a Data folder no longer stay at "Investigation pending".
- **Assistant-led:** unpacking a Wolf archive reports how many files it held, instead of "? files" and a total of 0.
