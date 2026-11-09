<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** translating a message again with **Skip already translated text** off no longer sends its speech's English as its text, or the speech as a name, where Assistant-led or a translation file wrote it over its rows, such as a name on a row of its own and its speech, and collecting speaker names no longer takes that speech for a name either: each is sent with its own Japanese, as the translation file lists it; runs estimated before this version send what they were approved with.
