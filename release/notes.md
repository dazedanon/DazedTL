<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Inspect run:** a Batch request's Response tab shows the Original and Translation table, as a Live one does, instead of the reply's raw JSON, and the request list is wide enough to read "Passed, 12 lines kept in Japanese" on one line.
- **Progress:** after changing a game from Guided steps to Assistant-led, Progress no longer says your assistant has started preparing the game before you have copied its prompt.

- **Translate:** opening the Images tab no longer shifts the stage strip and task tabs sideways; only the image grid and preview use the full window width.
- **Release:** on a VX Ace game, undoing or going back to a checkpoint no longer makes Release say "The game's data is older than ace_json" and hold Review & build patch ZIP until Pack outside edits; Data an assistant or another tool edited still waits for Pack outside edits.
