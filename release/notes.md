<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Assistant-led:** on WOLF, Unity, TyranoScript and other games that Text QA can't read, the assistant now checks its translations with Text QA's text rules, such as glossary names, changed numbers and untranslated lines, and corrects each problem or notes why the line is right.

### Fixed

- **Assistant-led:** a translation that drops a line's colour, sound or other control code, such as `\C[2]` or `\SE[...]`, or closes a colour before it opens is now refused, or kept in its original text in an API run, as Guided does, so the game no longer shows wrong colours, raw codes or a missing sound; runs already written into the game are not reopened.
- **Translation:** a moan the model leaves with small kana in an English line, such as `milk゛ぅぅぅ♡`, is now written as `milk゛uuu♡` instead of being sent again or kept in Japanese, in Guided and Assistant-led alike; runs started before keep their lines as they were.
