<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Images:** BMP, JPEG and KiriKiri TLG images are listed and translated too, not only PNG files, in every game but RPG Maker MV and MZ, and **Apply to game** writes each back in its own format; without a chosen image folder, Images also looks in the game's data folder. In Assistant-led, the assistant can unpack a KiriKiri game's unencrypted archives and pack the translated images into a patch.xp3.

### Changed

- **Context:** when your assistant changes a guidance file while you have a draft of it, **Save** shows your draft beside the file and asks which to keep, in **Guidance** and in Assistant-led's **Context**, which now show the same tabs, names and saved state; a draft of the **Assistant notes** holds up only copying a task to your assistant, no longer estimates, runs or approval.

### Fixed

- **Database:** the currency unit after an amount of money, such as 円, and the variable names a plugin draws, such as LL_VariableWindow's label, are now translated in Guided and Assistant-led alike, while other variable names stay as they are, since plugins and scripts may look a variable up by its name; an already translated game shows them as lines left in System.json until its next Database run.
- **Context:** a guidance file DazedTL can't read, such as an `AGENTS.md` that Windows PowerShell saved in another encoding, now says why on its tab instead of the tab disappearing, and the other files still save; **Go back** no longer lists a **Save Assistant notes** checkpoint as taken out.
