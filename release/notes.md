<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Release:** the patch ZIP no longer carries the game repository's `.gitignore`, `.gitattributes` and `README.md` at its root.
- **Inspect run:** a Batch request's Response tab shows the Original and Translation table, as a Live one does, instead of the reply's raw JSON, and the request list is wide enough to read "Passed, 12 lines kept in Japanese" on one line.
- **Progress:** after changing a game from Guided steps to Assistant-led, Progress no longer says your assistant has started preparing the game before you have copied its prompt.

- **Translate:** opening the Images tab no longer shifts the stage strip and task tabs sideways; only the image grid and preview use the full window width.
- **Game updates:** previewing an update of a VX Ace game no longer says its translated data files are "replaced by official binary file" when the update packs them from the merged text, and it lists the release's `Game.rgss3a` as replacing the archive kept for patches.
