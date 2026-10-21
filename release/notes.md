<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Context:** cost estimates made before this update read outdated once and refresh on the next estimate, because Maps & events now sends less; runs already approved or sent carry on as they were.

### Fixed

- **Maps & events:** text that is already finished is no longer sent again on every run: a line the game wrote in English inside 【】, whose translation replaced the game's own English, a translated message whose only Japanese is inside a plugin code such as `\SA[...]`, map names and event labels from map notes; those labels (`<LB>`, `<LB:...>`, `<namePop:...>`, `<dn:...>`) now count in **Lines**, so a map no longer reads done with them still in Japanese.
- **Maps & events:** an event label from a map note (`<LB:...>`, `<namePop:...>`, `<dn:...>`) now translates only the label and leaves the note's other tags alone: `<dn:古びた井戸><Shadow:false>` no longer loses `<Shadow:false>`, and `<dn:井戸><Sound:井戸>` keeps its sound name.
- **Translate:** once every saved translation is in the game, **Apply** is disabled with "Saved translations applied." beside it, and Translate on finished files shows "No new translation requests" in a small dialog instead of a tall, mostly empty one.
