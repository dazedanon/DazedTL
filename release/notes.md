<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Assistant-led:** when lines of a scene are translated again while the rest of it keeps its earlier translation, such as after a glossary edit, each request now shows the lines just before them with their earlier translation, as Guided does, so the new lines carry on the scene's voice and tense instead of reading as a scene of their own.

### Fixed

- **Assistant-led:** undoing “Apply translated images” in Checkpoints, or going back past it, now puts back the original of an image in a folder the assistant decoded from the game's archives instead of deleting it, so packing the archive again no longer loses that picture, for images prepared from this version on.
