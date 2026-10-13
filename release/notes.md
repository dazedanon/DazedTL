<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** Claude Batch and Live translation on Windows no longer fail with "Could not determine home directory.", and Claude cost estimates there use Claude's own token count instead of an approximate one.
- **Translate:** the **Live** cost review for a Claude model now counts input tokens the way Anthropic bills them, as the Batch review has since 2.11.2; it still read about 10% low. When Anthropic's token count can't be reached, the review says the input is approximate.
- **Translate:** a Batch that failed before anything was sent, for example because its connection could not be set up, now reads "Failed · unsent" in Run history instead of "Check submission", and translating those files again no longer warns that it may charge twice.
- **Translate:** when a newer run exists, the warning about a Batch that could not be confirmed as sent now names that Batch by its start time instead of calling it the last Batch.
- **Translate:** starting a cost estimate no longer shows "The operation could not finish." or leaves the cost review stuck on "Preparing the Batch cost review…".
