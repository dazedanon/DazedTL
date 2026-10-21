<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Project page:** a new **Checkpoints** tab lists every change DazedTL made to the game by version and stage, shows what each changed line by line, and can go back to one, undo one or save a copy of the game as it was then; it replaces **Versions**, whose game updates it now holds, and **Backups**, whose **Recover files…** **Save a copy…** replaces.
- **Translation:** DazedTL saves every change it makes to the game, such as an Apply, a Plugin files change, Line widths or Text QA's corrections, as its own checkpoint in the game's Git history, and saves edits you make outside DazedTL as a checkpoint of their own, so **Review translation checkpoint**, **Save translation version**, **Save version** and **Not committed yet** are gone.
- **Assistant-led:** DazedTL saves your assistant's changes to the game as checkpoints itself, one each time it reports a phase and one when a translation run ends, so your assistant no longer saves them, and writing a whole game's text makes one checkpoint instead of one per file.
- **Translate:** the new glossary terms a finished run adds are saved as that run's checkpoint instead of **Edits made outside DazedTL**.
- **Guided:** one **Save guidance** click saves as one checkpoint naming the documents it saved, and saving options or Line widths you left at the game's defaults no longer adds a **Save Line widths** checkpoint.
- **Set up:** DazedTL keeps a copy of the original game files in the game folder's Git history before its first change, which you never publish, and takes no more backups, so **Back up the original** is gone; games set up earlier keep using their backups.
