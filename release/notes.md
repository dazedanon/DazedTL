<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Assistant-led:** Mistral, Custom / local and Google Gemini connections ask for replies in the same format as Guided steps when translating Live, so a server that works in one works in the other.

### Fixed

- **Translate** and **Assistant-led:** a game saved on Batch, opened on a connection that can't run Batch such as DeepSeek, translates Live and says why beside the method, instead of a red "This connection does not support Batch." banner and a disabled Translate, or an API Batch card that could still be chosen and saved.
