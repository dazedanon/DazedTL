<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Assistant-led:** on OpenAI Batch, a clarification sent after a refusal now waits for room in the account's Batch token allowance, shared with Guided runs, instead of failing at OpenAI when the allowance is full.
- **Assistant-led:** lines saved by older versions as a refusal note such as "Declined." no longer count as translated; Progress shows them left and the next run translates them again.
- **Assistant-led:** the assistant writes RPG Maker MV/MZ text with DazedTL's own writer, which fits it to the game's windows, instead of an older tool that could leave long lines cut off.
- **Assistant-led:** text problems the final playtest finds after QA now go to another round of QA, as in Guided, and **Progress** keeps QA at **Final check** until the playtest settles instead of marking it done.
