<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Inspect run:** Lines left shows a line the model left in Japanese with its Japanese text (and its speaker) under Source text, instead of only the speaker or "-".
- **Line widths:** clearing a width field with select all and Backspace leaves it empty while you type, instead of showing "0" so that typing 44 reads "044".
- **Set up:** after you press Stop, setup now reads as stopped in a neutral note, not as red error text with "Prepare game files" marked Blocked.
- **Guided steps:** when a result beside a button, such as Save line widths, runs to two lines, the second line starts under the words instead of under the check mark.
- **Checkpoints:** **Copy assets & finish** no longer stops with "Pending asset update is invalid" after a game update's record of its assets was damaged, which left every game change refused.
- **Release:** after going back in Checkpoints to the files a patch ZIP was built from, Last saved patch ZIP no longer reads "Outdated · Game files changed since this build".
