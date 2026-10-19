<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Text QA:** your assistant can now fix crashes and windows too small for English that the playtest finds, in a fixes plugin of DazedTL's own; DazedTL puts it into the game only after playing the game with it breaks nothing new, and **History** on the Project page takes it out again with **Review restore**.
- **Plugin files:** Japanese plugin text the playtest saw on screen goes back to your assistant to decide again, with where it showed.

### Changed

- **Text QA:** for MV and MZ games the Text QA task is now also the final check: your assistant plays the game while QA reviews it, fixes what the playtest finds and plays it again after QA's corrections, so you copy one task instead of running the playtest yourself; the separate **Playtest** task is gone, and its panel shows under Text QA's.
- **Playtest:** places your assistant adds, such as a recollection room, are kept, and every later playtest visits them.
- **Assistant-led:** your assistant fixes crashes and windows too small for English that the playtest finds in the same fixes plugin instead of editing the game's code; DazedTL puts each fix into the game only after playing it with the fix breaks nothing new, then saves it as a version, so the patch always carries it.

### Fixed

- **Playtest:** a place your assistant added that the playtest could not play no longer shows as "A script failed" in the game's code; it is listed with what the playtest did not reach.
- **Playtest:** item and skill descriptions longer than two lines no longer go to Text QA as cut off unless the playtest saw them cut off, as in games whose help window shows three lines or draws its own text; text a plugin adds beside a description, such as a line of stats, no longer counts as the description's.
- **Text QA:** running QA again while its review is still going, such as after a plugin change, continues the same review instead of starting a new one when the playtest found something since.
