<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Inspect run:** Lines left shows a line the model left in Japanese with its Japanese text (and its speaker) under Source text, instead of only the speaker or "-".
- **Line widths:** clearing a width field with select all and Backspace leaves it empty while you type, instead of showing "0" so that typing 44 reads "044".
- **Set up:** after you press Stop, setup now reads as stopped in a neutral note, not as red error text with "Prepare game files" marked Blocked.
- **Stop:** pressing Stop in Set up, Line widths, Cost estimate or Release now says what was kept and whether running it again continues or starts over, instead of "Completed writes were retained; review the destination before retrying."
