<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Project:** the **×** beside a game in the project menu, or under **Recent projects**, removes it from the list, closing it if it is open. Its work stays, and opening the game again brings it back.
- **Translate:** choosing another model shows an estimate at that model's prices at once, without estimating again, when it sends the same requests, as most models of a connection do apart from Claude's. **Cost estimate** stays current, and the Batch and Live review windows have their own model menu; a Batch then prepares its requests for the new model before **Submit Batch**.
- **Assistant-led:** the API estimate waiting on **Progress** takes the new prices as soon as you choose another model or switch between **API Batch** and **Live API**, when its requests stay the same, and approving it sends them with your new choice. An estimate that needs new requests shows **Estimate again**, which prepares one without your assistant.

### Changed

- **Assistant-led:** only the approve button on **Progress** sends an API estimate. Your assistant can no longer start a run itself, even after you agree in its conversation; it waits for your approval instead. Each new estimate replaces the one waiting, so switching models while your assistant works no longer leaves several **API Batch** estimates to approve or cancel, and **History** shows an estimate only while it can be approved, with **Discard estimate** in place of **Cancel provider batch**, since nothing was sent.
- **Images:** the investigation no longer recommends images whose only text is a sound effect drawn into a scene, such as moans or hearts in event CGs, or marks them **Uncertain** when their marks might be sound effects. They read **Skipped · Sound effects only** under **All images**, where you can still tick one to translate it, and the translation task leaves sound effects as they are in images it translates for other text.

### Fixed

- **Assistant-led:** after you switch models with **Change** on **Progress**, the waiting estimate no longer keeps the previous model's price under the new model's name, ready to approve. It could show gpt-5.6-sol's $38.72 for gpt-5.6-terra until **Approve and submit Batch** refused it.
- **Cost estimate:** an unchanged estimate no longer reads **Outdated** after DazedTL restarts, where **Estimate again** then said "Nothing changed since the last estimate, so it is still current."
- **Translate:** the TOTAL at the end of a run's log now adds up every file in the run, including files translated before a resume, and the names translated before a Batch. It repeated the last file's own cost, so a run that cost $2.22 could read $0.0237, or $0.0000 when the last files needed no requests.
- **Translate:** an open **Inspect run** window now shows the Run log of a run that resumes or finishes while it is open, including its TOTAL. It kept the log from when it opened, so a resumed run could still end with "Translation failed!" until the window was closed and opened again.
- **Translate:** **Inspect run** no longer says "1 submission could not be confirmed" while a running run is still waiting on that request; it appears only once the run has stopped.
- **Translate:** lines an older run saved a refusal note for, such as "[Not translated: ...]" or "Translation declined.", are translated again. Those notes looked like finished English, so translating the file again sent nothing for them and the file read **Applied**; such files now read **Needs review** with the number of these lines, and **Translate** sends them, including map names and names shown by event label plugins.
- **Translate:** a file whose latest run had nothing left to send no longer shows the line count of an older run's unfinished work, such as "0 / 45" after a Batch that saved the file but failed on others; it counts every line as translated.
- **Translate:** a Batch waiting in **Review Batch submission** is sent only by **Submit Batch**. An Assistant-led assistant could submit it while the review still showed it unsent.
- **Project:** an Assistant-led run's **Inspect run** button in **History** (formerly **Inspect requests and results**) opens a window over the page with the run's requests and, on a **Batches** tab, its provider Batches, which the run itself now counts in one line instead of listing every ID. The requests opened below every run, out of sight once the page was scrolled, so the button seemed to do nothing. A run that cannot start, pause, cancel or discard its estimate now says why beside its buttons instead of at the top of the page.
- **Translate:** a Batch of **Maps & events** now counts each map's name toward that map's lines. All names were counted under the first map, so it could read **Needs review**, such as "8 / 9", for another map's refused name, while the maps named lacked their name line and a map with only a name showed no line count.
- **Translate:** **Inspect run**'s Run log no longer shows lines such as "MISMATCH_EVENT:Map001.json"; the "validation mismatch" lines after each file still say which files kept original text.
- **Images:** an image's tooltip and **Compare** show what the investigation found, such as **No text found**, again instead of "Make this image editable before starting image work.", a step the translation task now takes itself.
