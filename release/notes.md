<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** in a WOLF RPG game, a speaker name the model returned untranslated inside a colour code, such as `\c[2]セルリア`, is no longer kept as its translation, so the Japanese name no longer ships.
- **Translate:** in a Japanese game translated into Chinese, Maps & events no longer counts a translated event label or map name as a line left, so the map reads finished.
- **Translate:** Apply counts only the files it has left to apply, instead of keeping a count beside "Nothing new to apply." or "Saved translations applied.".
- **Check:** in a Japanese game translated into Chinese, the playtest no longer lists translated plugin settings and custom data as text never translated.
