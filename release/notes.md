<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Text QA:** your assistant can now fix crashes and windows too small for English that the playtest finds, in a fixes plugin of DazedTL's own; DazedTL puts it into the game only after playing the game with it breaks nothing new, and **History** on the Project page takes it out again with **Review restore**.
- **Plugin files:** Japanese plugin text the playtest saw on screen goes back to your assistant to decide again, with where it showed.

### Changed

- **Text QA:** for MV and MZ games the Text QA task is now also the final check: your assistant plays the game while QA reviews it, fixes what the playtest finds and plays it again after QA's corrections, so you copy one task instead of running the playtest yourself; the separate **Playtest** task is gone, and its panel shows under Text QA's.
- **Playtest:** places your assistant adds, such as a recollection room, are kept, and every later playtest visits them.
- **Assistant-led:** your assistant fixes crashes and windows too small for English that the playtest finds in the same fixes plugin instead of editing the game's code; DazedTL puts each fix into the game only after playing it with the fix breaks nothing new, then saves it as a version, so the patch always carries it.

### Fixed

- **Apply:** a game's own scripts that build text, such as a score line, are no longer rewrapped when you apply or save new Line widths; a line break in one stopped the game with "SyntaxError".
- **Assistant-led:** saving the playtest's fixes no longer fails with "Supply the matching untranslated original" for js/main.js, as in a game you moved, and **Start over** sets the earlier attempt's fixes aside.
- **Assistant-led:** patches always carry the update check and Forge plugins and the GameUpdate files Set up installs; a patch whose file list left them out made players' game stop at start with "Failed to load".
- **Assistant-led:** saving a translation version now stops and names the plugin when the patch's plugin list loads one that neither the patch nor players' game has, such as a plugin your assistant wrote, instead of making a patch that stops their game at start.
- **Game updates:** an update that changes js/main.js keeps loading the playtest's fixes, and saving a version stops when js/main.js and the fixes don't go together, instead of making a patch that crashes or loses the fixes.
- **Line widths:** saving new widths rewraps only text DazedTL applied, leaving files you translated another way as they are; **History** on the Project page undoes it with **Review restore**, and the next Apply no longer says those files were edited in the game.
- **Line widths:** English beside a note tag left in Japanese and English with "・" bullets now fit their windows, a list in an item's description keeps one item a line, and accented letters such as é count as one character.
- **Playtest:** a place your assistant added that the playtest could not play no longer shows as "A script failed" in the game's code; it is listed with what the playtest did not reach.
- **Playtest:** item and skill descriptions longer than two lines no longer go to Text QA as cut off unless the playtest saw them cut off, as in games whose help window shows three lines or draws its own text; text a plugin adds beside a description, such as a line of stats, no longer counts as the description's.
- **Project:** the **Status** tab of an Assistant-led game shows its latest activity once, in the status card, instead of repeating it below as "Last activity".
- **Text QA:** a damaged settings file in the game folder no longer stops **Start text QA**.
- **Text QA:** running QA again, such as after a plugin change, continues the same review instead of starting a new one when the playtest found something, also once the review is finished; lines a later playtest finds are reviewed on their own.
- **VX Ace:** games start with their own windows' widths, 52 characters and 40 beside a face, instead of MV and MZ's 60, which ran past the window's edge; an Ace game still on the old widths switches when you open it, and Assistant-led assistants measure Ace windows too.
- **VX Ace:** translated map names now reach the packed game.
