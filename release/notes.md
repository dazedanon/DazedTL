<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Batch:** a large game's Batch no longer makes the app use more memory each time its saved requests change while it waits.
- **Languages:** a Chinese target named Simplified Chinese, Traditional Chinese, 中文 or a code such as zh-CN now reads as Chinese, so a Japanese game's Chinese translation no longer reads as Japanese left; Settings and Set up now refuse a target language DazedTL doesn't know instead of treating it as English-like text.
- **Text QA:** a Japanese game translated into Chinese no longer has every line flagged as Japanese left. Saved Text QA work in review prepares again once after this update; finished work keeps its results.
- **Translation:** a Japanese game translated into Chinese no longer sends its map names and event labels again on every Translate, and Lines and Text QA read them as translated.
- **Translation:** a model that refuses in Chinese or Japanese, such as 抱歉，我无法翻译这段内容。, is now caught as a refusal instead of being kept as game text.
