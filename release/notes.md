<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Inspect run:** Lines left shows a line the model left in Japanese with its Japanese text (and its speaker) under Source text, instead of only the speaker or "-".
- **Line widths:** clearing a width field with select all and Backspace leaves it empty while you type, instead of showing "0" so that typing 44 reads "044".
- **Set up:** after you press Stop, setup now reads as stopped in a neutral note, not as red error text with "Prepare game files" marked Blocked.
- **Guided steps:** when a result beside a button, such as Save line widths, runs to two lines, the second line starts under the words instead of under the check mark.
- **Checkpoints:** **Copy assets & finish** no longer stops with "Pending asset update is invalid" after a game update's record of its assets was damaged, which left every game change refused.
- **Release:** after going back in Checkpoints to the files a patch ZIP was built from, Last saved patch ZIP no longer reads "Outdated · Game files changed since this build".
- **Inspect run:** an open Choose request list stays under its field when a row appears above the field, instead of staying put and covering it.
- **Translate:** a task no longer shows its done mark while files still read **Ready to apply**, such as after **Start over** or a new **Other event text** run, and **Other event text** no longer reads files only **Maps & events** translated as **Applied** with no lines.
- **Assistant-led:** the game folder notice looks like the one in Guided steps (an amber note, not a red banner), and a game update stopped partway says "A game update was interrupted. Finish the interrupted update, or cancel it, under Checkpoints to continue." instead of "unfinished Git cherry-pick".
- **Stop:** pressing Stop in Set up, Line widths, Cost estimate or Release now says what was kept and whether running it again continues or starts over, instead of "Completed writes were retained; review the destination before retrying."
- **Line widths:** unsaved width edits can be undone with **Discard draft**, as in Guidance.
- **Cost estimate:** after you stop an estimate, a note beside the button says it was stopped and nothing was saved, instead of the page quietly going back to Not started.
- **Translate:** after a game update, **Apply** is unavailable while a file it would apply reads **Outdated**, with "Reload changed files from the game first." beside it, instead of putting the old translation over the update's file.
- **Checkpoints:** a game update's review no longer lists `Forge_MZ.js` and `plugins.js` as the release's changes, and applying it no longer installs Forge into a game that didn't have it.
- **Translate:** **Other event text** offers **Apply** only for its own translated files, so before its first run it no longer shows a disabled **Apply (2)** with "Saved translations applied." for files **Maps & events** applied.
- **Plugin files:** after **Start over**, "Ready to apply" shows once, in the Assistant task header, not also on the Translated plugin text row; other assistant tasks no longer repeat their state on a row either.
- **Translate:** after a game update, one changed file reads "Reload it from the game", and "1 file reloaded from the game." goes away once you translate or apply.
