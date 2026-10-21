<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Context:** cost estimates made before this update read outdated once and refresh on the next estimate, because Maps & events now sends less; runs already approved or sent carry on as they were.

### Fixed

- **Maps & events:** text that is already finished is no longer sent again on every run: a line the game wrote in English inside 【】, whose translation replaced the game's own English, a translated message whose only Japanese is inside a plugin code such as `\SA[...]`, map names and event labels from map notes; those labels (`<LB>`, `<LB:...>`, `<namePop:...>`, `<dn:...>`) now count in **Lines**, so a map no longer reads done with them still in Japanese.
- **Maps & events:** an event label from a map note (`<LB:...>`, `<namePop:...>`, `<dn:...>`) now translates only the label and leaves the note's other tags alone: `<dn:古びた井戸><Shadow:false>` no longer loses `<Shadow:false>`, and `<dn:井戸><Sound:井戸>` keeps its sound name.
- **Line widths:** choice help translated in pieces around the game's own page number, such as "(1/3)", is now listed as not fitting when all of it needs more rows than the message window shows; before, each piece was checked alone and the cut-off rows went unreported.
- **Text QA:** a translated line whose only Japanese is inside a plugin code such as `\SA[...]` no longer reads as Japanese left in the text or as never translated, matching **Lines**.
- **Translate:** once every saved translation is in the game, **Apply** is disabled with "Saved translations applied." beside it, and Translate on finished files shows "No new translation requests" in a small dialog instead of a tall, mostly empty one.
- **Release:** a VX Ace game whose folder is named in Japanese now opens Release with a clean game ZIP name it can build, the folder name in English letters or `translated-game.zip`, instead of a rejected Japanese one; while a name is rejected, **View files & exclusions** says why beside it.
