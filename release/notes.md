<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Plugin files:** **Apply to game** writes the translated plugins in one click instead of opening a list of file names first; **Recovery** still restores them.
- **Text QA:** your assistant runs four reviewers at the same time instead of reviewing all the text itself, so QA finishes several times sooner; the time left follows how fast it really goes, and the activity line says **one reviewer at a time** when your assistant reviews alone.

### Fixed

- **Images:** an image investigation your assistant has saved only part of no longer reads finished and plays the notification while your assistant is still looking at the other images.
- **Player walkthrough:** an RPG Maker MV/MZ walkthrough no longer reads finished and plays the notification as soon as your assistant first saves `WALKTHROUGH.html`; it waits until your assistant's validation of the last saved page passes, and Release says when the page is saved but not validated yet or validation found errors.
