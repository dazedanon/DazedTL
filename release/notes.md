<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Assistant-led:** **Progress** and the project's run list show what an API run spent in dollars, beside its estimate.

### Fixed

- **Assistant-led:** counting an RPG Maker MV/MZ game's text no longer stops at a broken event command in its data; the rest of the file is counted as before.
- **Images:** when a scan or a new image folder brings images your assistant hasn't examined yet, **Images** now asks to investigate them instead of reading **Done**, as the assistant's `images --status` already did, and look-alike image families only group images in the folder **Images** reads.
- **Assistant-led:** your assistant no longer translates plugins the game never runs, such as turned-off plugins, a plugin listed a second time, or DazedTL's own Forge plugin, and leaves alone the choice help names MPP_ChoiceEX finds its help by; in a project counted before, **Progress** reads the text count as out of date until your assistant counts again.
- **Comment text:** a plugin listed a second time, such as a repeated MPP_ChoiceEX, no longer makes Maps & events, Text QA or the playtest read comments the game never shows as choice help.
- **Images:** an empty list of images to translate no longer reads "Nothing left to translate" before your assistant has examined the images, or after **Choose images myself** while none are ticked; it says what it waits for instead.
- **Assistant-led:** a translation that collapsed to a mark, repeats without end or still holds Japanese is no longer saved, as in Guided; an API run leaves just that line as the game wrote it and saves the rest of its request, so you never pay for them again, and the text written into the game gets the same small spacing fixes Guided makes, on every engine.
- **Assistant-led:** API estimates are priced as Guided prices its own: an OpenAI Batch estimate counts the prompt cache, so a GPT-5.6 or later Batch no longer reads below what it can cost, and an estimate for a model whose thinking is billed as output says it isn't included.
