<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Assistant-led:** your assistant now keeps a translation's words together in plugin commands and note tags by the same rule as Guided's Event text sources, and learns which commands a space split into more parts than their Japanese, so a plugin no longer shows only the first word; both methods choose a no-break space only where the game's font draws one.
- **Assistant-led:** translations now reach the game cleaned as Guided cleans them: curly apostrophes, 。, 【】, stray っ and em dashes take the forms Japanese fonts draw well, corner brackets become quotes under Convert Japanese quotation marks, and messages get a space after ! or ? and before pause codes; runs already written into the game are not reopened.

### Fixed

- **Assistant-led:** a translation that drops a line's colour, sound or other control code, such as `\C[2]` or `\SE[...]`, or closes a colour before it opens is now refused, or kept in its original text in an API run, as Guided does, so the game no longer shows wrong colours, raw codes or a missing sound; runs already written into the game are not reopened.
