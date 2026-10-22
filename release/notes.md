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
- **Translate:** after a game update, **Apply** is unavailable while a file it would apply reads **Outdated**, with "Reload changed files from the game first." beside it, instead of putting the old translation over the update's file.
