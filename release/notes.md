<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Project page:** a new **Checkpoints** tab lists every change DazedTL made to the game by version and stage, shows what each changed line by line, and can go back to one, undo one or save a copy of the game as it was then; it replaces **Versions**, whose game updates it now holds, and **Backups**, whose **Recover files…** **Save a copy…** replaces.
- **Translation:** DazedTL saves every change it makes to the game, such as an Apply, a Plugin files change, Line widths or Text QA's corrections, as its own checkpoint in the game's Git history, and saves edits you make outside DazedTL as a checkpoint of their own, so **Review translation checkpoint**, **Save translation version**, **Save version** and **Not committed yet** are gone.
- **Assistant-led:** DazedTL saves your assistant's changes to the game as checkpoints itself, one each time it reports a phase and one when a translation run ends, so your assistant no longer saves them, and writing a whole game's text makes one checkpoint instead of one per file.
- **Translate:** the new glossary terms a finished run adds are saved as that run's checkpoint instead of **Edits made outside DazedTL**.
- **Guided:** one **Save guidance** click saves as one checkpoint naming the documents it saved, and saving options or Line widths you left at the game's defaults no longer adds a **Save Line widths** checkpoint.
- **History and Plugin files:** **Undo** takes out a batch of QA corrections, playtest fixes or rewrapping, or a Plugin files application under **Recovery**, in one click by undoing its checkpoint, instead of a reviewed restore from copies DazedTL saved; batches applied earlier keep **Review restore**.
- **Images:** **Restore originals…** puts the original images back from the game's Git history, so preparing an image no longer saves a copy of it.
- **Assistant-led:** **Start over** puts the original game back as a new checkpoint, so the earlier attempt stays under **Checkpoints** instead of its Git history moving to `.dazedtl/archived`.
- **Set up:** DazedTL keeps a copy of the original game files in the game folder's Git history before its first change, which you never publish, and takes no more backups, so **Back up the original** is gone; games set up earlier keep using their backups.

### Fixed

- **Translate:** a reply with one line still in Japanese no longer throws away the whole request: only that line keeps its original text, **Inspect** names it, and the next Translate sends it again; a kaomoji such as (ﾟдﾟ) the model keeps from the source no longer counts as Japanese.
- **Checkpoints:** undoing a change or going back past it now shows QA corrections, Plugin files changes and translated images as undone in **History** and their tasks too, and undoing that undo shows them applied again.
- **Images:** **Restore originals…** now says when it is done, and an image it put back reads **Needs review** with what to do instead of "No image in your list is translated yet."
- **Release:** building the patch ZIP after a game update no longer fails with "The untranslated source baseline changed. Prepare a new request plan for this game version."
- **Text QA:** undoing QA corrections after applying Plugin files no longer leaves Text QA reading **Outdated** with the corrections hidden; it offers them again.
- **History and Checkpoints:** rows name the checkpoint an undo or go back acted on, undoing an undo reads **Redid** instead of nesting titles, batches undone since read **Undone**, **Other activity** stays open when you come back, and **Status** counts a Plugin files apply as the last activity.
- **Plugin files:** **Recovery** lists each application once, reading **Undone** once it is taken out, instead of adding a row for every undo and redo from **Checkpoints**.
