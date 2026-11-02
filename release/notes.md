<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Guide:** the user guide opens inside DazedTL from **Guide** in the sidebar, with its sections beside the text and a search; help on checkpoints, API keys, GameUpdate, speaker names and Assistant-led progress has a **Learn more** link to its section.
- **Settings:** a **Credits** tab thanks the people who built DazedTL and DazedMTLTool, the tool it grew from.
- **Sidebar:** **Share a fix** copies a task for your assistant to write up a fix it made in your game, to post on Discord so DazedTL can handle games like it by itself; the guide's new **Contributing** section explains it.

### Fixed

- **Images:** an image your assistant's investigation excluded no longer reads Skipped once you tick it, so **Copy translation task** includes it instead of saying the translation skipped every image.
- **Images:** resuming an image Batch translation no longer stops with "This connection does not support provider batch jobs." while an OpenRouter connection's check has failed or a connection without Batch is selected; it keeps the settings it started with.
- **Maps & events:** in a project set up by an older version, a speaker whose English name holds a `]` no longer leaves its `[Name]:` label at the start of the message, and an LL_GalgeChoiceWindow or LL_GalgeChoiceWindowMV choice that comes back with too few or too many answers no longer fails the map or writes the wrong choices, is not sent and paid for a second time in a run started after updating, and no longer writes one choice's translation inside another choice that holds its text, such as はい inside はいはい.
- **Translate:** a reply with too few or too many lines for a Text, Tyrano, Kirikiri, Regex or JSON file now keeps those lines in Japanese and reports the mismatch, where it wrote its translations onto the wrong lines and a Tyrano file with choices failed; a line that comes back untranslated keeps its original text instead of being rewritten with its line breaks turned into spaces.
- **Translate:** an empty Tyrano choice or Kirikiri tag pair no longer gets a translation between every letter of its line, an empty Lune field is no longer filled, a Tyrano or Kirikiri line read two ways no longer leaves later lines untranslated, moves their translations or pays to send them again, and a Tyrano file ending in a choice no longer fails.
- **Translate:** a CSV cell with two furigana, such as `＜漢字＝かんじ＞と＜仮名＝かな＞だ`, is now sent as `漢字と仮名だ`; a Regex `\text` block after a `"name"` line is no longer sent as said by that speaker, and one with no `\endtext` now fails its file with a message naming the block.
