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
- **Release:** on a VX Ace game, undoing or going back to a checkpoint no longer makes Release say "The game's data is older than ace_json" and hold Review & build patch ZIP until Pack outside edits; Data an assistant or another tool edited still waits for Pack outside edits.
- **Game updates:** previewing an update of a VX Ace game no longer says its translated data files are "replaced by official binary file" when the update packs them from the merged text, and it lists the release's `Game.rgss3a` as replacing the archive kept for patches.
- **Line widths:** going back to or undoing a checkpoint from before Save line widths now puts Line widths back to the widths the game uses again, instead of still showing the saved ones, so saving them again fits the text.
- **Game updates:** **Apply update** no longer flashes "Finish the interrupted update" with both buttons disabled while it runs; the preview and the Last saved patch ZIP card no longer repeat the same status two or three times.
- **Guidance:** saving after editing only Style & quirks names the checkpoint "Save Style & quirks" instead of also listing an untouched Game context; while a stopped game update holds the game folder, Save guidance and Save line widths are unavailable with "Resolve the game folder notice above first." only when they have something to save, instead of Save line widths failing after the click.
- **Translate:** **Apply** on Maps & events now puts in the files' newest translations, including Other event text's saved output for the same files, instead of copying the earlier run's files again while saying "Saved translations applied." and leaving the files at **Ready to apply**; its review names the files that carry another task's translations, and only Run history's Reapply says "Reapplying makes no API requests."
