<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Project:** the **×** beside a game in the project menu, or under **Recent projects**, removes it from the list, closing it if it is open. Its work stays, and opening the game again brings it back.

### Fixed

- **Translate:** the TOTAL at the end of a run's log now adds up every file in the run, including files translated before a resume, and the names translated before a Batch. It repeated the last file's own cost, so a run that cost $2.22 could read $0.0237, or $0.0000 when the last files needed no requests.
- **Translate:** an open **Inspect run** window now shows the Run log of a run that resumes or finishes while it is open, including its TOTAL. It kept the log from when it opened, so a resumed run could still end with "Translation failed!" until the window was closed and opened again.
- **Translate:** **Inspect run** no longer says "1 submission could not be confirmed" while a running run is still waiting on that request; it appears only once the run has stopped.
- **Translate:** lines an older run saved a refusal note for, such as "[Not translated: ...]" or "Translation declined.", are translated again. Those notes looked like finished English, so translating the file again sent nothing for them and the file read **Applied**; such files now read **Needs review** with the number of these lines, and **Translate** sends them, including map names and names shown by event label plugins.
- **Translate:** a file whose latest run had nothing left to send no longer shows the line count of an older run's unfinished work, such as "0 / 45" after a Batch that saved the file but failed on others; it counts every line as translated.
