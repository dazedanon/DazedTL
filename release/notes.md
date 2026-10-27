<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Playtest tools:** Remove TL Inspector now runs on one click, without a review dialog, since it only removes the Inspector's file from your computer.
- **Translate:** the Translate footer's guidance fits on one line, with Show more for the rest, instead of being cut off in a narrow window.
- **Project:** reopening a big game's workspace after a restart is faster.

### Fixed

- **Translate:** after a restart, Apply no longer says "Saved translations applied." when nothing new was applied; it now says "Nothing new to apply."
- **Translate:** while a big game's lines are still being counted, Apply and the Project page show "Counting…" instead of low file amounts, and Other event text no longer reads finished.
- **Cost estimate:** while event files are still being read after opening a game, the Other event text and whole-game estimates show they are being checked instead of reading not estimated or Outdated.
- **Plugin files:** in an English game, DazedTL's own update-check plugin is no longer offered for translation.
- **Context:** saving context with an older draft can no longer overwrite glossary entries a translation run or Text QA added after a failed save was recovered.
- **Dialogs:** a disabled text box is now dimmed like other disabled controls.
- **Batch:** a large game's Batch no longer makes the app use more memory each time its saved requests change while it waits.
- **Languages:** a Chinese target named Simplified Chinese, Traditional Chinese, 中文 or a code such as zh-CN now reads as Chinese, so a Japanese game's Chinese translation no longer reads as Japanese left; Settings and Set up now refuse a target language DazedTL doesn't know instead of treating it as English-like text.
- **Text QA:** a Japanese game translated into Chinese no longer has every line flagged as Japanese left. Saved Text QA work in review prepares again once after this update; finished work keeps its results.
- **Translation:** a Japanese game translated into Chinese no longer sends its map names and event labels again on every Translate, and Lines and Text QA read them as translated.
- **Translation:** a Japanese game translated into Simplified or Traditional Chinese now translates its speakers' dialogue lines instead of leaving them in Japanese, since a speaker's name written in hanzi is no longer read as untranslated.
- **Translation:** a model that refuses in Chinese or Japanese, such as 抱歉，我无法翻译这段内容。, is now caught as a refusal instead of being kept as game text.
