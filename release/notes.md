<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Glossary check:** a new Check task lists translated lines whose English doesn't use the glossary's English for a term in their Japanese, such as a place name translated before its glossary row existed; choose **Use proposal**, **Keep text** or **Write a fix** for each line or a whole term, then **Apply fixes**, which History on the Project page can restore.
- **Plugin files:** plugin labels Text QA finds too long for the screen, such as a menu command, now go to Plugin files: copy the task again and your assistant shortens each one or keeps it with its reason, then click **Apply to game**; Text QA's **Review them** shows where each label stands, with **Open Plugin files**.

### Changed

- **Set up:** your assistant measures the note width on the windows that show the notes DazedTL wraps, such as item detail notes, instead of the narrowest note window in the game, so wrapped notes no longer come out narrower than their window.

### Fixed

- **Translate:** translating an RPG Maker MV/MZ game's database keeps the line breaks in descriptions, profiles and detail notes; it ran each into one line and rewrapped it, so separate lines, such as a weapon's Weapon Skill line, ran into the text and blank rows between notes disappeared. **Line width check** and Text QA corrections keep those line breaks too.
- **Text QA:** **Review them** no longer lists plugin settings that Plugin files kept in Japanese on purpose, such as names a plugin looks up or text players never see, under **Never translated**, and **Playtest** no longer reports them as Japanese left in the game.
