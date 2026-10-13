<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** Claude Batch and Live translation on Windows no longer fail with "Could not determine home directory.", and Claude cost estimates there use Claude's own token count instead of an approximate one.
- **Translate:** the **Live** cost review for a Claude model now counts input tokens the way Anthropic bills them, as the Batch review has since 2.11.2; it still read about 10% low. When Anthropic's token count can't be reached, the review says the input is approximate.
