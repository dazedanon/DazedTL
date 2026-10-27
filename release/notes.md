<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Assistant-led:** a translation that collapsed to a mark, repeats without end or still holds Japanese is no longer saved, as in Guided; an API run marks its request failed instead, and the text written into the game gets the same small spacing fixes Guided makes, on every engine.
- **Assistant-led:** counting an RPG Maker MV/MZ game's text no longer stops at a broken event command in its data; the rest of the file is counted as before.
- **Images:** when a scan or a new image folder brings images your assistant hasn't examined yet, **Images** now asks to investigate them instead of reading **Done**, as the assistant's `images --status` already did, and look-alike image families only group images in the folder **Images** reads.
- **Assistant-led:** your assistant no longer translates plugins the game never runs, such as turned-off plugins, a plugin listed a second time, or DazedTL's own Forge plugin, and leaves alone the choice help names MPP_ChoiceEX finds its help by; in a project counted before, **Progress** reads the text count as out of date until your assistant counts again.
