<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Text QA:** each correction and question says what is wrong in one short, plain sentence; the reviewers' full reasoning moved to the History inspector, where QA's record also lists lines a reviewer found wrong but could not correct.
- **Text QA:** a question always offers the reviewer's proposal beside **Keep current text**; a problem no correction can fix is reported as not corrected instead of a question you could only keep, and never holds up applying the rest.

### Fixed

- **Text QA:** corrections to centered or instant-text messages that need an extra row are no longer refused, which had left lines such as a two-line event banner for you to fix by hand.
- **Text QA:** a name reviewers settled, such as "Demon Lord", no longer fights a glossary entry that says otherwise through round after round of review, ending as unverified.
- **Text QA:** two lines from one long scene go to one reviewer, so the scene is read once, lowering the cost on games with very long events.
- **Playtest:** a font change such as `\fn[和風]` no longer counts as Japanese left in translated text.
- **Playtest:** plugin strings **Plugin files** already settled, such as notetag names, are no longer reported again, which reopened the Plugin files task for nothing.
- **Playtest:** a battle window sized tightly to its text, such as Keke_PredictionSystem's action preview, no longer reads as text running past its bottom edge.
- **Playtest:** fixes written into the game are saved as a version of their own instead of riding along with the next Text QA apply, and the status says when the game runs other fixes than the ones you are editing.
