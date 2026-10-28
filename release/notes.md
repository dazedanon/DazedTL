<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Assistant-led:** a translation that drops a line's colour, sound or other control code, such as `\C[2]` or `\SE[...]`, or closes a colour before it opens is now refused, or kept in its original text in an API run, as Guided does, so the game no longer shows wrong colours, raw codes or a missing sound; runs already written into the game are not reopened.
