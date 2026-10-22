<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **History:** an Assistant-led game's History now lists its other activity, such as Start over, under Translation runs.
- **History:** Start over's row says how many files it put back instead of "0 files reloaded from the game".
- **Inspect run:** a Batch request's Response tab shows the Original and Translation table, as a Live one does, instead of the reply's raw JSON, and the request list is wide enough to read "Passed, 12 lines kept in Japanese" on one line.
- **Progress:** after changing a game from Guided steps to Assistant-led, Progress no longer says your assistant has started preparing the game before you have copied its prompt.
- **History:** Plugin files applies get a row under Other activity.
- **History:** the Database files and Maps & events applies are named for their task instead of both reading "Apply selected saved outputs", and History's Undo names the batch it undid.
- **Checkpoints:** after Go back or Undo, the result sits by the new top checkpoint; Save a copy's result no longer splits the folder's date and its Open folder link matches the message; the update header no longer reads "· complete" in lowercase.
- **Release:** the patch ZIP no longer carries the game repository's `.gitignore`, `.gitattributes` and `README.md` at its root.
- **Translate:** opening the Images tab no longer shifts the stage strip and task tabs sideways; only the image grid and preview use the full window width.
- **Footer:** a long running-operation message you expanded with **Show more** stays open as its progress changes, and a new error starts collapsed instead of opening like the last one.
