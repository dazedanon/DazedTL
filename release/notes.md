<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Checkpoints:** each change DazedTL makes to a game starts about a third fewer Git processes, so saves, applies and game updates finish sooner on Windows, where each process costs about 50 ms.

### Fixed

- **Context:** with a leftover `.git/index.lock` in the game folder, **Save context** now says so at once and leaves the file as it was; it took over a minute, saved the text anyway as "Edits made outside DazedTL", and saving the edited draft again then failed with "This guidance changed on disk. Reload before saving."
- **Menus:** a menu or help note no longer flashes in the window's top-left corner before it moves beside its button when the app is busy.
- **Fitting and Lines:** a Japanese game translated into Chinese is fitted to its windows and its lines read translated instead of being sent again, a Japanese translation of an English game that keeps HP is fitted, and Text QA no longer lists an English game's currency unit G as never translated. Saved Guided estimates need estimating again.
- **Text QA:** applying or undoing QA's own corrections, or applying Plugin files, no longer marks the task as changed text, so QA's later corrections apply.
- **Set up:** saving the first version of a game whose folder already had its own Git history, with all of it committed, no longer stops with "too many values to unpack (expected 2, got 3)".
- **Translate:** a model's refusal written as prose, such as "I won't produce this content, even in translation." or "Send another batch and I'll continue.", or as a bare "Declined.", is no longer accepted as dialogue, and Lines counts lines an earlier run saved that way as left, so the next Translate sends them again. Text QA no longer applies a correction that reads as a refusal.
- **Playtest tools:** installing TL Inspector no longer puts it in the game's `plugins.js`, where a translation published from the game stopped players' game at start with "Failed to load: js/plugins/TLInspector.js". The game's update check loads it on your computer instead, and opening a game an earlier version listed it in takes it out.
