<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Assistant-led:** Japanese that Text QA finds still untranslated where players can see it now goes back to your assistant, which translates it before QA's corrections are applied, instead of only naming it in its report.
- **Checkpoints:** each change DazedTL saves to a game starts half as many Git processes once DazedTL has saved one, and the Checkpoints tab, undo and go back start far fewer, so they finish sooner on Windows, where each process can take a tenth of a second.
