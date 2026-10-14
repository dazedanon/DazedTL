<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Settings:** Kimi (platform.kimi.ai) is a new provider. Kimi K2.6 and K2.7 Code can translate in a Batch at 40% off the Live price; Kimi K3 translates Live.

### Fixed

- **Translate:** a line that comes back as a refusal note, such as "[Not translated: …]", "[Omitted]" or "Translation declined.", now counts as a refusal. The request is asked again once with the context clarification; if the model still declines, its lines keep their original text and the file reads **Needs review**. These notes used to be saved as the translation.
- **Translate:** after stopping a Live run that translated several files at once (**Concurrent files** above 1 in settings carried over from an earlier version), every finished file counts as saved. Some used to read as not saved and were translated again.
- **Plugin files:** games whose plugin list repeats a plugin, such as an empty divider plugin listed many times, no longer stop **Copy plugin task** with "Duplicate configured plugins need investigation before exact scope can be formed."
- **Translate:** Batch cost estimates for large games finish sooner. Pricing the requests no longer takes several seconds twice per estimate, and each file no longer rebuilds the translation instructions from the game's guidance: a 972-file Maps & events Batch estimate on Windows took about 87 s instead of 99 s.
- **App:** when DazedTL cannot open its workspace at start, the page says why, such as the workspace already being open in another DazedTL, instead of "A newer version of DazedTL may fix this." under a second, sometimes vaguer message.
