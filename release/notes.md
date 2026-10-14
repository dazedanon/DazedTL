<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Project:** the **×** beside a game in the project menu, or under **Recent projects**, removes it from the list, closing it if it is open. Its work stays, and opening the game again brings it back.

### Changed

- **Assistant-led:** only the approve button on **Progress** sends an API estimate. Your assistant can no longer start a run itself, even after you agree in its conversation; it waits for your approval instead. Each new estimate replaces the one waiting, so switching models while your assistant works no longer leaves several **API Batch** estimates to approve or cancel, and **History** shows an estimate only while it can be approved, with **Discard estimate** in place of **Cancel provider batch**, since nothing was sent.

### Fixed

- **Translate:** the TOTAL at the end of a run's log now adds up every file in the run, including files translated before a resume, and the names translated before a Batch. It repeated the last file's own cost, so a run that cost $2.22 could read $0.0237, or $0.0000 when the last files needed no requests.
- **Translate:** an open **Inspect run** window now shows the Run log of a run that resumes or finishes while it is open, including its TOTAL. It kept the log from when it opened, so a resumed run could still end with "Translation failed!" until the window was closed and opened again.
- **Translate:** **Inspect run** no longer says "1 submission could not be confirmed" while a running run is still waiting on that request; it appears only once the run has stopped.
- **Translate:** lines an older run saved a refusal note for, such as "[Not translated: ...]" or "Translation declined.", are translated again. Those notes looked like finished English, so translating the file again sent nothing for them and the file read **Applied**; such files now read **Needs review** with the number of these lines, and **Translate** sends them, including map names and names shown by event label plugins.
- **Translate:** a file whose latest run had nothing left to send no longer shows the line count of an older run's unfinished work, such as "0 / 45" after a Batch that saved the file but failed on others; it counts every line as translated.
- **Translate:** a Batch waiting in **Review Batch submission** is sent only by **Submit Batch**. An Assistant-led assistant could submit it while the review still showed it unsent.
- **Project:** **Inspect requests and results** on an Assistant-led run in **History** opens its requests in a window over the page. They opened below every run, out of sight once the page was scrolled, so the button seemed to do nothing. **Attach matching provider job** opens its own window too, and a run that cannot start, pause, cancel or discard its estimate says why beside its buttons instead of at the top of the page.
- **Translate:** a Batch of **Maps & events** now counts each map's name toward that map's lines. All names were counted under the first map, so it could read **Needs review**, such as "8 / 9", for another map's refused name, while the maps named lacked their name line and a map with only a name showed no line count.
- **Translate:** **Inspect run**'s Run log no longer shows lines such as "MISMATCH_EVENT:Map001.json"; the "validation mismatch" lines after each file still say which files kept original text.
