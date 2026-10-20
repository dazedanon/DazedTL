<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Text QA:** your assistant can now fix crashes and windows too small for English that the playtest finds, in a fixes plugin of DazedTL's own; DazedTL puts it into the game only once a play of the game with it in place breaks nothing new, translation versions and patches always carry it, a game update that changes `js/main.js` keeps loading it, and **History** on the Project page takes it out again with **Review restore**.
- **Plugin files:** plugin text your assistant kept in Japanese goes back to it once to decide again when the playtest saw it on screen, with where it showed.
- **Plugin files:** VX Ace games get the task too: your assistant translates the text the game's scripts show, such as menu commands and battle messages, and Ace packing writes the applied scripts back into the game.
- **Assistant-led:** your assistant saves the **Line widths** it measures in the running game, VX Ace windows included, and DazedTL fits the text it writes to them, and what it already wrote when it saves new widths, without adding commands to the game's events, so saved games still load.
- **Assistant-led:** your assistant shortens plugin text that Text QA's screen captures show squeezed or cut off, such as a menu command, as **Plugin files** does in Guided steps.

### Changed

- **Text QA:** for MV and MZ games the Text QA task is now also the final check: your assistant plays the game while QA reviews it, fixes what the playtest finds and plays it again after QA's corrections, so you copy one task instead of running the playtest yourself; the separate **Playtest** task is gone, and its panel shows under Text QA's. For a game whose Text QA finished before this version, **Run QA again** has your assistant play it.
- **Text QA:** for MV and MZ games, **Assistant tasks** shows Text QA as **Waiting** until a playtest of the game as it now is leaves nothing more for your assistant, and only then does the Project page mark it done; a plugin change during QA, such as one of your assistant's fixes, reads **Waiting** instead of **Outdated**.
- **Text QA:** QA reviews only text it hasn't reviewed before or that changed since, including lines whose glossary entry changed, so running it again after an update or a few edits reviews just those, and the page says so, such as "17 lines checked · 799 unchanged since earlier QA"; tell your assistant which version was checked before you used DazedTL, and QA skips that text from then on. Its reviewers also need far fewer turns, so QA uses less of your assistant's plan.
- **Text QA:** the page shows only QA's progress, the questions it can't settle and its corrections; **Review them** and its lists are gone, and what QA did not cover, such as lines its reviewers declined and Japanese never translated, is in **History** on the Project page when you inspect **Prepare or resume translation QA**.
- **Text QA:** text the game squeezes only after QA finished goes to a follow-up round of review instead of a **Squeezed after QA** list.
- **Playtest:** places your assistant adds, such as a recollection room, are kept, and every later playtest visits them.
- **Assistant-led:** your assistant fixes crashes and windows too small for English that the playtest finds in the same fixes plugin instead of editing the game's code; DazedTL puts each fix into the game only once a play of the game with it in place breaks nothing new, then saves it as a version, so the patch always carries it.
- **Assistant-led:** your assistant keeps plot spoilers out of the messages it saves translation versions with, which players can read in the patch repository.

### Removed

- **Glossary check:** the Check task is gone; Text QA now puts the glossary's English into lines that write a term another way, such as a place name translated before its glossary row existed, and lists those corrections as **Glossary term**. Glossary fixes you applied earlier still restore from **History**.
- **Line width check:** the Check task is gone, as translation, **Apply** and Text QA now fit text to the **Line widths** themselves: they wrap like the Japanese where the English allows, count full-width marks such as ～ and ♥ as two characters, fit English beside a note tag left in Japanese, and leave the game's own scripts that build text, such as a score line, as they are, where the Line width check's rewrap could stop the game with "SyntaxError". Saving new widths after you apply rewraps the text DazedTL applied that no longer fits, which **History** restores with **Review restore**, and text a window cuts off even rewrapped goes to Text QA's reviewers to shorten.

### Fixed

- **History:** **Review restore** for QA corrections no longer stops at "Restore the newer text batch first." when a later batch, such as an **Apply** of other files, can't be restored; a batch restores once no later batch changed its files, and otherwise the button names the later batch to restore first, or says a later Apply replaced those files.
- **Plugin files:** **Apply to game** and **Review restore** now wait while a game update is stopped on conflicts, saying "The game folder has an unfinished Git cherry-pick. Finish or cancel it under Versions, or in Git, to continue." as **Apply** does; they wrote the game, after which **Cancel update & restore translation** failed with "error: Entry 'js/plugins.js' not uptodate". **Images** waits the same way.
- **Project:** the **Status** tab of an Assistant-led game shows its latest activity once, in the status card, instead of repeating it below as "Last activity", and building a clean game ZIP reads **Build clean game ZIP** in **History**, as on the Release page, instead of "Build public release ZIP".
- **Text QA:** running QA again, such as after a plugin change, continues the same review instead of starting a new one when the playtest found something, also once the review is finished; lines a later playtest finds are reviewed on their own.
- **Text QA:** a correction of a slip found in several lines, such as a quoted title that no longer matches, no longer gives as its reason the note its reviewer wrote on why some of those lines stay as they are.
- **Translate:** text an MV or MZ game keeps in a text variable no longer stops the game with "SyntaxError" when its translation holds a backtick, "${" in it shows as written, and a name code such as `\n[1]` or `\nc<Alice>` in it is kept; Text QA writes its corrections there the same way, wrapped to the list width in **Line widths**.
- **Text QA:** a correction that drops a name window code such as `\nc<Alice>` is refused, and a translated line that lost one goes to QA's reviewers.
- **Text QA:** a review left underway in the previous version keeps the read-through it had finished when your assistant picks it up after the update, instead of reading all that text again, also in games with text variables or name windows such as `\n<Alice>` and when its reviewers declined some lines.
- **Playtest:** **Problems** says where each text problem stands with Text QA: a line QA can't take reads "Not in QA's review" instead of "Text QA corrects it when QA runs again" forever, and a line QA corrected that the playtest still flags, or that QA reviewed only for another reason, goes to QA's next round instead of reading "Text QA reviewed it".
- **Playtest:** a place your assistant added that the playtest could not play no longer shows as "A script failed" in the game's code; it is listed with what the playtest did not reach.
- **Playtest:** item and skill descriptions longer than two lines no longer go to Text QA as cut off unless the playtest saw them cut off, as in games whose help window shows three lines or draws its own text; text a plugin adds beside a description, such as a line of stats, no longer counts as the description's.
- **Playtest:** in MZ games that use MessageWindowPopup, the layout check your assistant runs to measure **Line widths** and the playtest's message checks no longer fail with "Cannot read properties of undefined (reading 'rtl')".
- **Assistant-led:** patches always carry the update check and Forge plugins and the GameUpdate files Set up installs; a patch whose file list left them out made players' game stop at start with "Failed to load".
- **Assistant-led:** saving a translation version now stops and names the plugin when the patch's plugin list loads one that neither the patch nor players' game has, such as a plugin your assistant wrote, instead of making a patch that stops their game at start.
- **Assistant-led:** messages above the page, such as a warning or a failed action, line up with the panels below instead of sticking out past their right edge, as do error messages in **Settings** and above any page; a failed **Run playtest again** shows its error only beside the button.
- **Backups:** progress counts one file as "1 file" instead of "1 files", as when Start over puts back its first file.
- **Windows:** scripts your assistant writes over game text no longer crash with a 'charmap' UnicodeEncodeError: every copied task tells it to run them with DazedTL's own Python.
- **Release:** a VX Ace game in a clean game ZIP no longer stops on English Windows with "RGSS301.dll File corrupted" when its folder had a Japanese name: the game's folder inside every clean game ZIP now takes the archive's name, without `.zip`, instead of the game folder's, and Release asks for a VX Ace game's ZIP name in English letters.
- **VX Ace:** **Database files** no longer fails with "KeyError: 0".
- **VX Ace:** **Images** finds the game's images in `Graphics` instead of asking you to choose a folder.
- **VX Ace:** your assistant's **Event text sources** findings are no longer refused once the game is translated.
- **VX Ace:** a patch ZIP with translated images in `Graphics` no longer fails to build.
- **VX Ace:** the packed game no longer freezes at an event that sets a text variable, also in a game translated with an earlier version: **Release** asks each VX Ace game to pack again with **Review native Ace packing**, which writes the text variables an earlier version translated so the game reads them.
- **VX Ace:** the packed game's window shows the translated title instead of the Japanese one; packing puts it into `Game.ini` in plain letters.
- **VX Ace:** games start with their own windows' widths, 52 characters and 40 beside a face, instead of MV and MZ's 60 and 50, which ran past the window's edge; a Guided Ace game still on the old widths switches when you open it, and the text you applied is fitted to them.
- **VX Ace:** translated map names now reach the packed game.
