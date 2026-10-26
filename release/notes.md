<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Playtest tools:** installing TL Inspector no longer puts it in the game's `plugins.js`, where a translation published from the game stopped players' game at start with "Failed to load: js/plugins/TLInspector.js". The game's update check loads it on your computer instead, and opening a game an earlier version listed it in takes it out.
- **Context:** with a leftover `.git/index.lock` in the game folder, **Save context** now says so at once and leaves the file as it was; it took over a minute, saved the text anyway as "Edits made outside DazedTL", and saving the edited draft again then failed with "This guidance changed on disk. Reload before saving."
- **Menus:** a menu or help note no longer flashes in the window's top-left corner before it moves beside its button when the app is busy.
- **Fitting and Lines:** a Japanese game translated into Chinese is fitted to its windows and its lines read translated instead of being sent again, a Japanese translation of an English game that keeps HP is fitted, and Text QA no longer lists an English game's currency unit G as never translated. Saved Guided estimates need estimating again.
