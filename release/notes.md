<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** names and labels translated with Live before a Batch now join the game glossary in **Context** > **Guidance** even when you decline the Batch, so you can see and edit them there. Completed runs already added them.

### Fixed

- **Translate:** Claude Batch and Live translation on Windows no longer fail with "Could not determine home directory.", and Claude cost estimates there use Claude's own token count instead of an approximate one.
- **Translate:** for a Claude model, the **Live** cost review and **Review names and labels** now count input tokens the way Anthropic bills them, as the Batch review has since 2.11.2; they read about 10% and a third low. When Anthropic's token count can't be reached, the review says the input is approximate.
- **Translate:** a Batch that failed before anything was sent, for example because its connection could not be set up, now reads "Failed · unsent" in Run history instead of "Check submission", and translating those files again no longer warns that it may charge twice.
- **Translate:** when a newer run exists, the warning about a Batch that could not be confirmed as sent now names that Batch by its start time instead of calling it the last Batch.
- **Translate:** starting a cost estimate no longer shows "The operation could not finish." or leaves the cost review stuck on "Preparing the Batch cost review…". If that error appears for another reason while work runs, it now clears by itself once DazedTL can read the project again, instead of progress freezing until you reload.
- **Translate:** names and labels translated with Live before a Batch are no longer lost when one of them has its own parentheses, such as "Farmer's Soul (Husband)". The Batch review said "Name translation result unavailable", and the next run asked to pay for every name again. Names from those earlier runs are now reused, and a name that still can't be saved is listed on its own instead of discarding the rest.
- **Context:** glossary entries whose translation has its own parentheses, such as `ヴィクター（釣り竿） (Victor (Fishing Rod))`, now reach translation; they were ignored before.
