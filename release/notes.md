<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Check:** a new Playtest task plays an RPG Maker MV/MZ game in a hidden window before release: the title, New Game, the opening, every menu screen, a save and a load, a shop, a battle and the screens plugins add.
- **Check:** the Playtest reports crashes, Japanese left in the game and text that doesn't fit, with a capture of each problem it saw on screen, and checks the files for data or plugins that don't load, lost names and codes such as \N[1] or %1, and descriptions longer than their help window.
- **Check:** problems the Playtest finds in translated text go to Text QA's review and are corrected like QA's own findings; run the Playtest again to see what is fixed and what is new.
- **Assistant-led:** your assistant can run the Playtest before release, add stops of its own, and fix what it finds; a Playtest tab shows the report once it has run.
- **Text QA:** preparing QA captures the game's interface screens, so text the game squeezes or cuts off goes to review with its captures, and the Text QA page lists what QA can't correct, such as a plugin's menu.
- **Text QA:** corrections are rewrapped to fit the game's text boxes as the line width check would, and a correction that needs more rows than its box is refused.
- **Line widths:** Message rows, the number of rows one message window shows, is saved beside the widths.
- **Set up:** your assistant confirms the measured line widths in the running game and corrects values the game clips, squeezes or wraps.

### Changed

- **Release:** a clean game ZIP holds only the game's files and its translation; notes, downloaded pages or dictionaries left in the game folder stay out and are listed in the review.
- **Text QA:** finds more battle messages that lost the battler's name, including ones that start with a capital letter.

### Fixed

- **Release:** game and patch ZIPs no longer hold file names Windows can't extract, and their files no longer extract as readable only by you.
- **Set up:** a game backup that stopped with "Backup entries must use safe relative file paths." now names the file to rename or move.
- **Text QA:** a line that is one 「」 quotation is no longer mistaken for a title and overwritten.
