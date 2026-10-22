<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a kaomoji with half-width marks, such as (ﾟдﾟ), no longer comes back with its eyes stacked on the mouth or as a box, and a short line such as え？ that the model gives back untranslated is no longer saved as translated; it keeps its original text and the next Translate sends it again.
