<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Project page:** a new **Checkpoints** tab lists every change DazedTL made to the game by version and stage, shows what each changed line by line, and can go back to one, undo one or save a copy of the game as it was then; it replaces the **Versions** tab, whose game updates now start here, and the **Backups** tab; to get an old state of the game, use **Save a copy…** on a checkpoint.
- **Translation:** DazedTL saves every change it makes to the game, such as an Apply, a Plugin files change, Line widths or Text QA's corrections, as its own checkpoint in the game's Git history, and saves edits you make outside DazedTL as a checkpoint of their own, so **Review translation checkpoint**, **Save translation version**, **Save version** and **Not committed yet** are gone.
- **Assistant-led:** DazedTL saves your assistant's changes to the game as checkpoints itself, one each time it reports a phase and one when a translation run ends, so your assistant no longer saves them.
- **Guided:** one **Save guidance** click saves as one checkpoint naming the documents it saved.
- **History and Plugin files:** **Undo** takes out a batch of QA corrections, playtest fixes or rewrapping, or a Plugin files application under **Recovery**, in one click by undoing its checkpoint, instead of a reviewed restore from copies DazedTL saved; it then reads **Undone**, and undoing it again from **Checkpoints** reads **Redid**. Batches applied earlier keep **Review restore**.
- **Images:** **Restore originals…** puts the original images back from the game's Git history, so preparing an image no longer saves a copy of it.
- **Assistant-led:** **Start over** puts the original game back as a new checkpoint, so the earlier attempt stays under **Checkpoints** instead of its Git history moving to `.dazedtl/archived`.
- **Set up:** DazedTL keeps a copy of the original game files in the game folder's Git history before its first change, kept privately and never pushed with your translation, and takes no more backups, so **Back up the original** is gone. Games set up earlier keep using their backups, which stay in the game's `.dazedtl/backups` folder; the user guide's **Backups from before checkpoints** explains how to restore them.
- **Translate:** cost estimates made before updating read as outdated once and need estimating again; runs you already approved or sent keep going.

### Fixed

- **Translate:** a reply with one line still in Japanese no longer throws away the whole request: only that line keeps its original text, **Inspect** names it, and the next Translate sends it again; a kaomoji such as (ﾟдﾟ) the model keeps from the source no longer counts as Japanese.
- **Images:** **Restore originals…** now says when it is done, and an image it put back reads **Needs review** with what to do instead of "No image in your list is translated yet."
- **Release:** building the patch ZIP after a game update no longer fails with "The untranslated source baseline changed. Prepare a new request plan for this game version."
- **Text QA:** undoing QA corrections after applying Plugin files no longer leaves Text QA reading **Outdated** with the corrections hidden; it offers them again.
- **History:** **Other activity** stays open when you come back, and **Status** counts a Plugin files apply as the last activity.
