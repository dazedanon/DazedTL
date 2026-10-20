<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Text QA:** once QA is prepared again, the assistant can no longer go on with the task it replaced, which had reported a new round as finished while nobody reviewed it.
- **Text QA:** a choice reviewers settled in an earlier QA of the game, such as "Demon Lord", carries into later rounds, which no longer raise the same glossary fixes again.
- **Text QA:** a line the playtest still flags because its correction never reached the game, such as a weapon description cut off in its help window, comes back in the next round instead of reading as reviewed.
- **Fitting:** a message's list keeps one item a row when an item needs a second row, instead of running two items together, which Text QA's own check then flagged.
