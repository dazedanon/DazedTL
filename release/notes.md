<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Text QA:** once QA is prepared again, the assistant can no longer go on with the task it replaced, which had reported a new round as finished while nobody reviewed it.
- **Text QA:** a choice reviewers settled in an earlier QA of the game, such as "Demon Lord", carries into later rounds, which no longer raise the same glossary fixes again.
- **Text QA:** a line the playtest still flags because its correction never reached the game, such as a weapon description cut off in its help window, comes back in the next round instead of reading as reviewed.
- **Fitting:** a message's list keeps one item a row when an item needs a second row, instead of running two items together, which Text QA's own check then flagged.
- **Playtest:** Japanese that another window draws while a message is open, such as a choice's help or a map HUD, is no longer reported as the message's line for Text QA, where it read "Not in QA's review"; text that was never translated is sent to translation instead, and a choice's help points to **Maps & events** with **Comment text** on.
- **Maps & events:** the help a choice shows from event comments, such as MPP_ChoiceEX's 選択肢ヘルプ, is now translated: Guided turns **Comment text** on for games that show it, projects you already have included, and each help line wraps to the message window instead of running past its edge.
- **Maps & events:** choice help shown beside a portrait wraps to the **With portrait** width, and Apply, new Line widths and Text QA corrections rewrap translated help that no longer fits, keeping its event commands.
- **Text QA:** the playtest shows each choice's help before choosing, and reports help too tall for the message window, whose first rows players never see.
- **Text QA:** the never-translated report and the playtest list choice help that was never translated everywhere in the game, not only where the playtest happened to see it, and no longer list the plugin setting naming these comments as text to translate.
