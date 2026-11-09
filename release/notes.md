<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Compare:** a new page in the sidebar translates a few lines of your game with up to four models side by side, from any of your connections, or one model with a changed thinking effort, glossary or instruction, sent as a real run sends them, so you can pick a model in equal conditions; **Blind** hides the names until you've picked the best line of each.

### Fixed

- **Translate:** translating a message again with **Skip already translated text** off no longer sends a quest name such as 【柚月の心残り】 on the message's second line as a speaker and leaves it out of the text, or sends the English of a row after a blank first row as that row's text, where Assistant-led, a translation file or an earlier run wrote it, and with **First-line names** on a translated name before speech goes to the speaker step whatever its speech's English opens with: each text is sent with its own Japanese and speaker, as the translation file lists it; runs estimated before this version send what they were approved with.
