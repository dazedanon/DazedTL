<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Settings:** the Credits tab is one shorter list that names each person once, with V2 marking work on DazedTL and V1 work on DazedMTLTool, the tool it grew from.

### Fixed

- **Translate:** a Gemini Batch sent before 2.52.4 on a Custom Gemini-compatible connection, whose replies held refusals, no longer stops at "Reconcile the clarification Batch submission."; its refused lines are asked again at Google, where that Batch was sent, with the same connection's key.
