<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Plugin files:** a quest subject set by code (`this.txtSubject = …`) no longer sends the next string on its line as the subject, and a drawn label such as `\\}回数\\{` after another drawn label in the same `drawTextEx` call is translated instead of left in Japanese.
