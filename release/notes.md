<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** while a Batch runs, its waiting line now says how many requests are done or failed out of those sent and how many Batches have finished, and that the files fill in when every Batch finishes.
- **Translate:** a reply with too few or too many lines for a Text, Tyrano, Kirikiri, Regex or JSON file now keeps those lines in Japanese and reports the mismatch, where it wrote its translations onto the wrong lines and a Tyrano file with choices failed; a line that comes back untranslated keeps its original text instead of being rewritten with its line breaks turned into spaces.
- **Translate:** an empty Tyrano choice or Kirikiri tag pair no longer gets a translation between every letter of its line, an empty Lune field is no longer filled, a Tyrano or Kirikiri line read two ways no longer leaves later lines untranslated, moves their translations or pays to send them again, and a Tyrano file ending in a choice no longer fails.
- **Translate:** a CSV cell with two furigana, such as `＜漢字＝かんじ＞と＜仮名＝かな＞だ`, is now sent as `漢字と仮名だ`; a Regex `\text` block after a `"name"` line is no longer sent as said by that speaker, and one with no `\endtext` now fails its file with a message naming the block.
- **Maps & events:** an LL_GalgeChoiceWindowMV choice translated with a comma, such as "Sure, sure", no longer becomes two choices in the game and moves the choices after it onto the wrong branches, and the plugin command keeps its other text as it was; in a run started after updating, its choices are sent with the question their menu shows.
