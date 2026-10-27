<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Assistant-led:** **Progress** and the project's run list show what an API run spent in dollars, beside its estimate.
- **GameUpdate:** in Assistant-led, your assistant now adds GameUpdate to WOLF, Unity and TyranoScript games too, so players can update the patch; a WOLF translation then ships its data loose in the `Data` folder, since GameUpdate takes out a repacked `Data.wolf`.
- **Assistant-led:** a **Release** tab builds a clean game ZIP, or saves your assistant's patch ZIP under a name and folder you choose, as Guided's Release does, for any engine; once your assistant has packaged the patch, the **Patch** phase on **Progress** shows its ZIP with **Open folder**, marked **Outdated** after an undo, a game update or a new write, and until the patch is ready, **Release** says what your assistant still has to finish.

### Changed

- **Release:** a patch ZIP built from the translation version you pushed for GameUpdate now carries its GameUpdate configuration, as the clean game ZIP does, so players who extract it can update with GameUpdate later.

### Fixed

- **Release:** a clean game ZIP or patch ZIP now reads **Outdated** after a game update, a write or an undo that only adds files, such as new maps, instead of **Done**, in Guided and Assistant-led.
- **Assistant-led:** counting an RPG Maker MV/MZ game's text no longer stops at a broken event command in its data; the rest of the file is counted as before.
- **Images:** when a scan or a new image folder brings images your assistant hasn't examined yet, **Images** now asks to investigate them instead of reading **Done**, as the assistant's `images --status` already did, and look-alike image families only group images in the folder **Images** reads.
- **Assistant-led:** your assistant no longer translates plugins the game never runs, such as turned-off plugins, a plugin listed a second time, or DazedTL's own Forge plugin, and leaves alone the choice help names MPP_ChoiceEX finds its help by; in a project counted before, **Progress** reads the text count as out of date until your assistant counts again.
- **Comment text:** a plugin listed a second time, such as a repeated MPP_ChoiceEX, no longer makes Maps & events, Text QA or the playtest read comments the game never shows as choice help.
- **Images:** an empty list of images to translate no longer reads "Nothing left to translate" before your assistant has examined the images, or after **Choose images myself** while none are ticked; it says what it waits for instead.
- **Assistant-led:** a translation that collapsed to a mark, repeats without end or still holds Japanese is no longer saved, as in Guided; an API run leaves just that line as the game wrote it and saves the rest of its request, so you never pay for them again, and the text written into the game gets the same small spacing fixes Guided makes, on every engine.
- **Translate:** a line a run translated as only its game codes and a mark, such as a lone period between two codes, is translated again by the next run instead of kept. Cost estimates made before updating read as outdated once and count those lines; runs you already approved or sent keep going as they were estimated.
- **Assistant-led:** API estimates are priced as Guided prices its own: an OpenAI Batch estimate counts the prompt cache, so a GPT-5.6 or later Batch no longer reads below what it can cost, and an estimate for a model whose thinking is billed as output says it isn't included.
- **Translate:** a canceled or expired OpenAI-compatible Batch records the prompt cache it read apart from other input, as a finished one does, so what it spent reads as the provider bills it.
