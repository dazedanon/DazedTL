<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Release:** building a patch ZIP no longer stops with "Add exact player image or font paths under img/, Graphics/ or fonts/" after **Images** applied a picture kept in another folder, such as a VX Ace game's images folder; the patch now carries it.
- **Translate:** translating a message again with **Skip already translated text** off no longer shows part of it twice where one of its rows opens with a code such as `\SE[1]`, as in messages Assistant-led wrote: each part is sent with its own Japanese, as a translation file lists it, and written once; runs estimated before this version send what they were approved with.
