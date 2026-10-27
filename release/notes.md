<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Assistant-led:** a **Release** tab builds a clean game ZIP, or saves your assistant's patch ZIP under a name and folder you choose, as Guided's Release does, for any engine; once your assistant has packaged the patch, the **Patch** phase on **Progress** shows its ZIP with **Open folder**.
- **GameUpdate:** in Assistant-led, your assistant now adds GameUpdate to WOLF, Unity and TyranoScript games too, so players can update the patch; a WOLF translation then ships its data loose in the `Data` folder, since GameUpdate takes out a repacked `Data.wolf`.

### Changed

- **Release:** a patch ZIP built from the translation version you pushed for GameUpdate now carries its GameUpdate configuration, as the clean game ZIP does, so players who extract it can update with GameUpdate later.

### Fixed

- **Assistant-led:** counting an RPG Maker MV/MZ game's text no longer stops at a broken event command in its data; the rest of the file is counted as before.
- **Images:** when a scan or a new image folder brings images your assistant hasn't examined yet, **Images** now asks to investigate them instead of reading **Done**, as the assistant's `images --status` already did, and look-alike image families only group images in the folder **Images** reads.
- **Assistant-led:** your assistant no longer translates plugins the game never runs, such as turned-off plugins, a plugin listed a second time, or DazedTL's own Forge plugin, and leaves alone the choice help names MPP_ChoiceEX finds its help by; in a project counted before, **Progress** reads the text count as out of date until your assistant counts again.
- **Comment text:** a plugin listed a second time, such as a repeated MPP_ChoiceEX, no longer makes Maps & events, Text QA or the playtest read comments the game never shows as choice help.
- **Images:** an empty list of images to translate no longer reads "Nothing left to translate" before your assistant has examined the images, or after **Choose images myself** while none are ticked; it says what it waits for instead.
