<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Text QA:** a line that drops a censor mask (〇 or ●) its Japanese has, or adds one it lacks, and a he or she that contradicts a character's gender in the glossary now go to a reviewer, in both methods; saved Text QA reads outdated once.

### Fixed

- **Assistant-led:** RPG Maker MV and MZ messages that open with a name window, such as `\n<Ellen>`, no longer get a stray space before a pause code that follows it.
- **Messages:** RPG Maker MV and MZ messages no longer get a stray space between a colour or other formatting code and a pause code after it, which could start a line with a space.
