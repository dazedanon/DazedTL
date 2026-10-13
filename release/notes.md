<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Context:** the new **Cost estimate** task shows what translating the whole game with your API key costs before you translate anything: Database files, Maps & events and Other event text over all their files, each with its cost, in Batch or Live. It is free, and it reads **Outdated** once the guidance, sources, game files or model change.

### Changed

- **Context:** the Other event text investigation and its **Source choices** moved from Translate to a new Context task, **Event text sources**, so the sources are chosen before the cost estimate; **Other event text** in Translate now only translates them.
- **Context:** **Event text sources** findings now keep spaces in translated plugin labels and popups where the plugin allows it, instead of underscores, and leave placeholders untranslated instead of turning off their whole source; investigate again in games already in progress.

### Fixed

- **Translate:** **Other event text** no longer says "Saved translations applied." after Maps & events is applied, before its own translations are.
