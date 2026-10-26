<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Context:** with a leftover `.git/index.lock` in the game folder, **Save context** now says so at once and leaves the file as it was; it took over a minute, saved the text anyway as "Edits made outside DazedTL", and saving the edited draft again then failed with "This guidance changed on disk. Reload before saving."
- **Menus:** a menu or help note no longer flashes in the window's top-left corner before it moves beside its button when the app is busy.
