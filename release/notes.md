<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Assistant-led:** Japanese that Text QA finds still untranslated where players can see it now goes back to your assistant, which translates it before QA's corrections are applied, instead of only naming it in its report.
- **Checkpoints:** each change DazedTL saves to a game starts half as many Git processes once DazedTL has saved one, and the Checkpoints tab, undo and go back start far fewer, so they finish sooner on Windows, where each process can take a tenth of a second.
- **Set up:** the glossary Set up writes, in both methods, follows three more naming rules: no Lord or Lady for characters whose gender the game leaves open, the right direction for gauges where high is bad, such as "Lowers Lewdness by 5", and lowercase creature words such as "slimes" in dialogue.

### Fixed

- **Playtest:** a game the playtest can't play, such as one without its engine's scripts, now reads Skipped with the reason once the final check ends without a play, instead of Blocked while Text QA and Progress read done.
