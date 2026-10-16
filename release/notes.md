<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Plugin files:** your assistant now checks each plugin label it shortens in the game itself: DazedTL plays the game in a hidden window with the shorter text, without changing the game, and a label counts as shortened only once it fits on its screen, so a shorter label that is still squeezed, or that the game draws from another setting, goes back to your assistant.

### Changed

- **Text QA:** running QA again after plugin files change opens the game's screens again and keeps the review done so far, so labels **Plugin files** shortened drop off **Review them** and labels still too long go back to it; game text the game squeezes only now goes to review, or once QA has finished, **Review them** lists it under **Squeezed after QA**.

### Fixed

- **Text QA:** **Review them** keeps **Never translated** up to date when you run QA again after plugin text changes, or when **Plugin files** decides to keep a setting in Japanese, instead of showing the list from when QA was first prepared.
- **Plugin files:** a plugin label Text QA finds too long no longer shows "In no plugin file" after a plugin file you applied earlier changed outside DazedTL, such as by a game update, while Plugin files read as complete.
