<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Context:** Guided's **Guidance** now has the **Assistant notes** tab too, so you can read and edit what your assistant keeps about the game in `AGENTS.md`.

### Changed

- **Text QA:** corrections and proposals show the text they change in red and green, with the changed words marked, as soon as they appear instead of only once applied.
- **Context:** when your assistant changes a guidance file while you have a draft of it, **Save** shows your draft beside the file and asks which to keep, in **Guidance** and in Assistant-led's **Context**, which now show the same tabs, names and saved state; a draft of the **Assistant notes** holds up only copying a task to your assistant, no longer estimates, runs or approval.

### Fixed

- **GameUpdate:** an update that fails partway, such as on a file the running game holds, a full disk or a folder too deep for Windows ("Could not find a part of the path"), now puts the game back as it was instead of leaving it half patched; a game gets this with its next copy of GameUpdate, such as from **Recreate GameUpdate files**.
- **Text QA:** reviews no longer propose a speaker fix that names the character in Japanese, which stopped **Apply corrections** with "QA regression failed; all game-file changes were rolled back"; a failed apply now names the correction that stopped it.
- **Context:** the **Assistant notes** (`AGENTS.md`) are no longer deleted by a game update when the game had them before Set up, are no longer saved with the files of new Assistant-led checkpoints, so undoing an older one no longer waits on a later one or brings back older notes, and an older Guided draft no longer replaces them; one another program holds no longer fails every change to the game, and on Windows an `agents.md` in another case no longer reaches players' downloads.
- **Context:** a guidance file DazedTL can't read, such as an `AGENTS.md` that Windows PowerShell saved in another encoding, now says why on its tab instead of the tab disappearing, and the other files still save; **Go back** no longer lists a **Save Assistant notes** checkpoint as taken out.
