<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Images:** BMP, JPEG and KiriKiri TLG images are listed and translated too, not only PNG files, in every game but RPG Maker MV and MZ, and **Apply to game** writes each back in its own format; without a chosen image folder, Images also looks in the game's data folder. In Assistant-led, the assistant can unpack a KiriKiri game's unencrypted archives and pack the translated images into a patch.xp3.

### Fixed

- **Database:** the currency unit after an amount of money, such as 円, and the variable names a plugin draws, such as LL_VariableWindow's label, are now translated in Guided and Assistant-led alike, while other variable names stay as they are, since plugins and scripts may look a variable up by its name; an already translated game shows them as lines left in System.json until its next Database run.
