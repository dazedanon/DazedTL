<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Images:** investigating is optional: tick the images to translate yourself to skip it, or click **Choose images myself** while your assistant investigates to stop it and keep what it found; before an investigation the list's tab reads **To translate** instead of **Recommended**.

### Fixed

- **Lines:** after the update, each game's line counts are read once more, so a Chinese or Japanese refusal note an earlier run left in place of a line counts as left to translate.
- **Text QA:** in a Japanese game translated into Chinese, Text QA now checks glossary terms too, so a line that writes a character's or term's name another way than the glossary, or leaves it out, is marked for review.
