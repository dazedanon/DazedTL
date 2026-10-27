<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Settings:** DeepSeek is a new provider, so a DeepSeek key no longer needs a Custom / local connection. DeepSeek translates Live; its models think before they answer, which isn't in the estimate.

### Fixed

- **Translate** and **Assistant-led:** a game saved on Batch, opened on a connection that can't run Batch such as DeepSeek, translates Live and says why beside the method, instead of a red "This connection does not support Batch." banner and a disabled Translate, or an API Batch card that could still be chosen and saved.
