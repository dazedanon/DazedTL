# Changelog

Every DazedTL release, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
[release.mjs](scripts/release.mjs) writes each entry from [release/notes.md](release/notes.md).

## [2.44.0] - 2026-10-28

### Added

- **Text QA:** a line that drops a censor mask (〇 or ●) its Japanese has, or adds one it lacks, and a he or she that contradicts a character's gender in the glossary now go to a reviewer, in both methods; saved Text QA reads outdated once.

### Fixed

- **Assistant-led:** a name the Japanese writes after a lone backslash, such as `\ヘレン`, no longer vanishes in RPG Maker MV and MZ once translated: it is written `\\Helen`, as Guided writes it, instead of `\Helen`, which the game reads as an unknown code.
- **Assistant-led:** a line that translates, drops or repeats a code holding a name, such as a font `\fn[...]`, a face `\face[...]` or a sound `_pum[...]`, is now refused as Guided refuses it; only a ruby may still be translated.
- **Assistant-led:** RPG Maker MV and MZ messages that open with a name window, such as `\n<Ellen>`, no longer get a stray space before a pause code that follows it.
- **Assistant-led:** lines of Japanese punctuation alone, such as `「……」` or `！？`, now reach the game as `"……"` and `!?`, as Guided writes them, instead of shipping in Japanese form, and they are never part of a cost estimate.
- **Messages:** RPG Maker MV and MZ messages no longer get a stray space between a colour or other formatting code and a pause code after it, which could start a line with a space.
- **Assistant-led:** images applied into a folder the assistant decoded from the game's archives no longer ship as loose files beside the archive they were packed into, in the patch ZIP, the clean game ZIP or GameUpdate's download; checkpoints still restore them.
- **Languages:** French, Spanish, Portuguese and other Latin-script translations keep their é instead of having it written as e, in both methods; English is written as before.

## [2.43.0] - 2026-10-27

### Added

- **Assistant-led:** on WOLF, Unity, TyranoScript and other games that Text QA can't read, the assistant now checks its translations with Text QA's text rules, such as glossary names, changed numbers and untranslated lines, and corrects each problem or notes why the line is right.

### Fixed

- **Assistant-led:** a translation that drops a line's colour, sound or other control code, such as `\C[2]` or `\SE[...]`, or closes a colour before it opens is now refused, or kept in its original text in an API run, as Guided does, so the game no longer shows wrong colours, raw codes or a missing sound; runs already written into the game are not reopened.
- **Translation:** a moan the model leaves with small kana in an English line, such as `milk゛ぅぅぅ♡`, is now written as `milk゛uuu♡` instead of being sent again or kept in Japanese, in Guided and Assistant-led alike; runs started before keep their lines as they were.
- **RPG Maker MV/MZ:** a game translated into English or another language written in Latin letters now gets the English locale from Guided's Apply too, so name entry offers Latin letters instead of kana, and Assistant-led keeps the game's own locale for other targets, such as Chinese, instead of switching it to English; games already applied change only on their next Apply or write.

## [2.42.0] - 2026-10-27

### Changed

- **Assistant-led:** your assistant now keeps a translation's words together in plugin commands and note tags by the same rule as Guided's Event text sources, and learns which commands a space split into more parts than their Japanese, so a plugin no longer shows only the first word; both methods choose a no-break space only where the game's font draws one.
- **Assistant-led:** translations now reach the game cleaned as Guided cleans them: curly apostrophes, 。, 【】, stray っ and em dashes take the forms Japanese fonts draw well, corner brackets become quotes under Convert Japanese quotation marks, and messages get a space after ! or ? and before pause codes; runs already written into the game are not reopened.

### Fixed

- **Assistant-led:** importing your assistant's glossary now adds its names and terms to the glossary's existing sections instead of a second Game Characters or Game Terms heading.

## [2.41.0] - 2026-10-27

### Changed

- **Assistant-led:** Japanese that Text QA finds still untranslated where players can see it now goes back to your assistant, which translates it before QA's corrections are applied, instead of only naming it in its report.
- **Checkpoints:** each change DazedTL saves to a game starts half as many Git processes once DazedTL has saved one, and the Checkpoints tab, undo and go back start far fewer, so they finish sooner on Windows, where each process can take a tenth of a second.
- **Set up:** the glossary Set up writes, in both methods, follows three more naming rules: no Lord or Lady for characters whose gender the game leaves open, the right direction for gauges where high is bad, such as "Lowers Lewdness by 5", and lowercase creature words such as "slimes" in dialogue.

### Fixed

- **Text QA:** Apply and Undo of a correction now work on a finished QA task prepared before Text QA recorded Line widths, instead of failing.
- **Playtest:** a game the playtest can't play, such as one without its engine's scripts, now reads Skipped with the reason once the final check ends without a play, instead of Blocked while Text QA and Progress read done.

## [2.40.2] - 2026-10-27

### Fixed

- **Translate** and **Assistant-led:** a line written as `Name「...」` in the game, also with the name in color or as a name code, no longer comes out as `Village Chief: "Welcome, traveler."` now and then; translations keep the game's own format, `Village Chief "Welcome, traveler."`, and Text QA fixes lines translated before.

## [2.40.1] - 2026-10-27

### Changed

- **Assistant-led:** Mistral, Custom / local and Google Gemini connections ask for replies in the same format as Guided steps when translating Live, so a server that works in one works in the other.

### Fixed

- **Translate** and **Assistant-led:** a game saved on Batch, opened on a connection that can't run Batch such as DeepSeek, translates Live and says why beside the method, instead of a red "This connection does not support Batch." banner and a disabled Translate, or an API Batch card that could still be chosen and saved.
- **Settings:** clicking Settings while DazedTL is still starting no longer shows "Workspace unavailable" or leaves "Wait for the workspace to open." on the Project page; Project and Settings open once the workspace has.

## [2.40.0] - 2026-10-27

### Added

- **Settings:** DeepSeek is a new provider, so a DeepSeek key no longer needs a Custom / local connection. DeepSeek translates Live; its models think before they answer, which isn't in the estimate.

## [2.39.0] - 2026-10-27

### Changed

- **Assistant-led:** an RPG Maker MV/MZ skill's battle messages, such as "%1 casts Fire!", now tell the model which characters and enemies use the skill, as Guided does, so it picks the right pronouns for them; an estimate still waiting for approval asks to be estimated again once.
- **Assistant-led:** when your assistant organizes the text again, such as after a glossary change or a game update, every line that already has a translation keeps it and the new estimate covers only the rest, as Guided does, and requests the provider would read word for word the same are sent once.

### Fixed

- **Assistant-led:** a line an API run left in Japanese because its translation failed counted as translated on **Progress** and was never sent again; it now reads as left, and your assistant's next estimate sends it on its own.

## [2.38.1] - 2026-10-27

### Fixed

- **Translate:** in an RPG Maker MV/MZ game whose messages start with `\m[N]\z[N]` codes, the first line of a longer message is now translated instead of staying in Japanese however often you translate again. Cost estimates made before updating read as outdated once; runs you already approved or sent keep going as they were estimated.

## [2.38.0] - 2026-10-27

### Added

- **Assistant-led:** **Progress** and the project's run list show what an API run spent in dollars, beside its estimate.
- **GameUpdate:** in Assistant-led, your assistant now adds GameUpdate to WOLF, Unity and TyranoScript games too, so players can update the patch; a WOLF translation then ships its data loose in the `Data` folder, since GameUpdate takes out a repacked `Data.wolf`.
- **Assistant-led:** a **Release** tab builds a clean game ZIP, or saves your assistant's patch ZIP under a name and folder you choose, as Guided's Release does, for any engine; once your assistant has packaged the patch, the **Patch** phase on **Progress** shows its ZIP with **Open folder**, marked **Outdated** after an undo, a game update or a new write, and until the patch is ready, **Release** says what your assistant still has to finish.

### Changed

- **Release:** a patch ZIP built from the translation version you pushed for GameUpdate now carries its GameUpdate configuration, as the clean game ZIP does, so players who extract it can update with GameUpdate later.

### Fixed

- **Release:** a clean game ZIP or patch ZIP now reads **Outdated** after a game update, a write or an undo that only adds files, such as new maps, instead of **Done**, in Guided and Assistant-led.
- **Assistant-led:** counting an RPG Maker MV/MZ game's text no longer stops at a broken event command in its data; the rest of the file is counted as before.
- **Images:** when a scan or a new image folder brings images your assistant hasn't examined yet, **Images** now asks to investigate them instead of reading **Done**, as the assistant's `images --status` already did, and look-alike image families only group images in the folder **Images** reads.
- **Assistant-led:** your assistant no longer translates plugins the game never runs, such as turned-off plugins, a plugin listed a second time, or DazedTL's own Forge plugin, and leaves alone the choice help names MPP_ChoiceEX finds its help by; in a project counted before, **Progress** reads the text count as out of date until your assistant counts again.
- **Comment text:** a plugin listed a second time, such as a repeated MPP_ChoiceEX, no longer makes Maps & events, Text QA or the playtest read comments the game never shows as choice help.
- **Images:** an empty list of images to translate no longer reads "Nothing left to translate" before your assistant has examined the images, or after **Choose images myself** while none are ticked; it says what it waits for instead.
- **Assistant-led:** a translation that collapsed to a mark, repeats without end or still holds Japanese is no longer saved, as in Guided; an API run leaves just that line as the game wrote it and saves the rest of its request, so you never pay for them again, and the text written into the game gets the same small spacing fixes Guided makes, on every engine.
- **Translate:** a line a run translated as only its game codes and a mark, such as a lone period between two codes, is translated again by the next run instead of kept. Cost estimates made before updating read as outdated once and count those lines; runs you already approved or sent keep going as they were estimated.
- **Assistant-led:** API estimates are priced as Guided prices its own: an OpenAI Batch estimate counts the prompt cache, so a GPT-5.6 or later Batch no longer reads below what it can cost, and an estimate for a model whose thinking is billed as output says it isn't included.
- **Translate:** a canceled or expired OpenAI-compatible Batch records the prompt cache it read apart from other input, as a finished one does, so what it spent reads as the provider bills it.

## [2.37.0] - 2026-10-27

### Added

- **Assistant-led:** on games that keep their images in archives, such as WOLF RPG Editor games, your assistant now translates them through DazedTL's **Images** steps on the folder it unpacks them into, with the same image checks and **Progress** counts as other games, then packs them back into the game.

### Fixed

- **Assistant-led:** **Copy post-update task** now has your assistant finish a game update the way it translated the game, in the project's mode and languages: it keeps the translations of lines the update left alone, waits for you to approve API costs on **Progress**, and runs QA, the playtest and the patch again, instead of editing the game's files by hand and translating everything itself, and copying it works after any finished update.
- **Versions:** A game with more than 100 checkpoints since its last version or update, such as after a long Assistant-led run, keeps its version, so Guided translation runs no longer refuse to start and ask you to set up the original and translation branches again.
- **Assistant-led:** on OpenAI Batch, each part of a run now waits for room in the account's Batch token allowance, shared with Guided runs, as its clarifications already did, and reads **Waiting for capacity** until it is sent; before, it was sent at once and could fail at OpenAI while a Guided Batch filled the allowance.
- **Assistant-led:** choice help that plugins such as MPP_ChoiceEX show from event comments now counts as text your assistant must translate, so a game no longer finishes with its choice help in Japanese while **Progress** reads all text as extracted; in a project counted before, **Progress** reads the text count as out of date until your assistant counts again.

## [2.36.4] - 2026-10-27

### Fixed

- **Assistant-led:** on OpenAI Batch, a clarification sent after a refusal now waits for room in the account's Batch token allowance, shared with Guided runs, instead of failing at OpenAI when the allowance is full.
- **Assistant-led:** lines saved by older versions as a refusal note such as "Declined." no longer count as translated; Progress shows them left and the next run translates them again.
- **Assistant-led:** the assistant writes RPG Maker MV/MZ text with DazedTL's own writer, which fits it to the game's windows, instead of an older tool that could leave long lines cut off.
- **Assistant-led:** text problems the final playtest finds after QA now go to another round of QA, as in Guided, and **Progress** keeps QA at **Final check** until the playtest settles instead of marking it done.
- **Assistant-led:** undoing the assistant's work under **Checkpoints**, or updating the game, reopens the steps on **Progress** that work no longer covers instead of leaving them done, and after a game update **Progress** says the text count is out of date and the patch waits until your assistant counts the game again.

## [2.36.3] - 2026-10-27

### Fixed

- **Checkpoints:** a game update given the game's current version that was cancelled or failed no longer leaves its release as the game's original files, which made some untranslated text read as translated and left it out of runs, patches and going back.

## [2.36.2] - 2026-10-27

### Fixed

- **Translate:** in a WOLF RPG game, a speaker name the model returned untranslated inside a colour code, such as `\c[2]セルリア`, is no longer kept as its translation, so the Japanese name no longer ships.
- **Translate:** in a Japanese game translated into Chinese, Maps & events no longer counts a translated event label or map name as a line left, so the map reads finished.
- **Translate:** Apply counts only the files it has left to apply, instead of keeping a count beside "Nothing new to apply." or "Saved translations applied.".
- **Check:** in a Japanese game translated into Chinese, the playtest no longer lists translated plugin settings and custom data as text never translated.

## [2.36.1] - 2026-10-27

### Fixed

- **Translate:** in a Japanese game translated into Chinese, plugin command text, scripts, event labels and map names that a translation kept in Chinese are no longer sent again on every run, and map names translated before 2.35.0 keep their Japanese source instead of being sent and changed once more.
- **Text QA:** in a Japanese game translated into Chinese, the list of text never translated no longer shows translated plugin settings, custom data and map names. A Text QA task still in review prepares again once after the update.

## [2.36.0] - 2026-10-26

### Changed

- **Images:** investigating is optional: tick the images to translate yourself to skip it, or click **Choose images myself** while your assistant investigates to stop it and keep what it found; before an investigation the list's tab reads **To translate** instead of **Recommended**.
- **Images:** big games open Images and switch between **Recommended**, **All images** and folders faster: thumbnails load near where you are looking instead of for the whole list, a thumbnail shown again isn't read from the game again, the grid no longer flashes empty and the tabs no longer shift.

### Fixed

- **Text QA:** in a Japanese game translated into Chinese, Text QA now checks glossary terms too, so a line that writes a character's or term's name another way than the glossary, or leaves it out, is marked for review.
- **Images:** results your assistant saves while you browse All images or a folder no longer jump the grid back to **Recommended** at the top.
- **Lines:** after the update, each game's line counts are read once more, so a Chinese or Japanese refusal note an earlier run left in place of a line counts as left to translate.

## [2.35.0] - 2026-10-26

### Changed

- **Playtest tools:** Remove TL Inspector now runs on one click, without a review dialog, since it only removes the Inspector's file from your computer.
- **Translate:** the Translate footer's guidance fits on one line, with Show more for the rest, instead of being cut off in a narrow window.
- **Project:** reopening a big game's workspace after a restart is faster.

### Fixed

- **Translate:** after a restart, Apply no longer says "Saved translations applied." when nothing new was applied; it now says "Nothing new to apply."
- **Translate:** while a big game's lines are still being counted, Apply and the Project page show "Counting…" instead of low file amounts, and Other event text no longer reads finished.
- **Cost estimate:** while event files are still being read after opening a game, the Other event text and whole-game estimates show they are being checked instead of reading not estimated or Outdated.
- **Plugin files:** in an English game, DazedTL's own update-check plugin is no longer offered for translation.
- **Context:** saving context with an older draft can no longer overwrite glossary entries a translation run or Text QA added after a failed save was recovered.
- **Dialogs:** a disabled text box is now dimmed like other disabled controls.
- **Batch:** a large game's Batch no longer makes the app use more memory each time its saved requests change while it waits.
- **Languages:** a Chinese target named Simplified Chinese, Traditional Chinese, 中文 or a code such as zh-CN now reads as Chinese, so a Japanese game's Chinese translation no longer reads as Japanese left; Settings and Set up now refuse a target language DazedTL doesn't know instead of treating it as English-like text.
- **Text QA:** a Japanese game translated into Chinese no longer has every line flagged as Japanese left. Saved Text QA work in review prepares again once after this update; finished work keeps its results.
- **Translation:** a Japanese game translated into Chinese no longer sends its map names and event labels again on every Translate, and Lines and Text QA read them as translated.
- **Translation:** a Japanese game translated into Simplified or Traditional Chinese now translates its speakers' dialogue lines instead of leaving them in Japanese, since a speaker's name written in hanzi is no longer read as untranslated.
- **Translation:** a model that refuses in Chinese or Japanese, such as 抱歉，我无法翻译这段内容。, is now caught as a refusal instead of being kept as game text.

## [2.34.5] - 2026-10-26

### Fixed

- **Projects:** a game moved or renamed after estimating keeps its Guided and whole-game cost estimates, and preparing Text QA again goes on with the task in review, whose instructions name the game's new folder.
- **Translate:** a model's refusal written as prose, such as "I won't produce this content, even in translation." or "Send another batch and I'll continue.", or as a bare "Declined.", is no longer accepted as dialogue, and Lines counts lines an earlier run saved that way as left, so the next Translate sends them again. Text QA no longer applies a correction that reads as a refusal.
- **Translate:** opening a big game's translation workspace no longer holds the whole app for seconds while it counts every file's lines and reads its event files; files still being counted read **Counting…**, and the counts are kept across restarts.

## [2.34.4] - 2026-10-26

### Changed

- **Checkpoints:** each change DazedTL makes to a game starts about a third fewer Git processes, so saves, applies and game updates finish sooner on Windows, where each process costs about 50 ms.

### Fixed

- **Context:** with a leftover `.git/index.lock` in the game folder, **Save context** now says so at once and leaves the file as it was; it took over a minute, saved the text anyway as "Edits made outside DazedTL", and saving the edited draft again then failed with "This guidance changed on disk. Reload before saving."
- **Menus:** a menu or help note no longer flashes in the window's top-left corner before it moves beside its button when the app is busy.
- **Fitting and Lines:** a Japanese game translated into Chinese is fitted to its windows and its lines read translated instead of being sent again, a Japanese translation of an English game that keeps HP is fitted, and Text QA no longer lists an English game's currency unit G as never translated. Saved Guided estimates need estimating again.
- **Text QA:** applying or undoing QA's own corrections, or applying Plugin files, no longer marks the task as changed text, so QA's later corrections apply.
- **Set up:** saving the first version of a game whose folder already had its own Git history, with all of it committed, no longer stops with "too many values to unpack (expected 2, got 3)".
- **Playtest tools:** installing TL Inspector no longer puts it in the game's `plugins.js`, where a translation published from the game stopped players' game at start with "Failed to load: js/plugins/TLInspector.js". The game's update check loads it on your computer instead, and opening a game an earlier version listed it in takes it out.

## [2.34.3] - 2026-10-26

### Fixed

- **Context:** a failed **Save context** shows its reason beside the button, and it and any other failed file write now name the file and why (for example that it is read-only), and a leftover Git lock says another Git process is using the game instead of "The operation could not finish."
- **Inspect:** in **File contents**, every line after a message of more than one row showed beside another line's source text; each message now shows as one line beside its own source.
- **Playtest tools:** installing or removing TL Inspector or Forge no longer says so twice or makes the window jump.
- **Forge:** quick load (Ctrl+Q) no longer crashes some games with an error screen right after loading, such as "Cannot read properties of undefined (reading 'massCharacters')".
- **Settings:** a successful **Check connection** no longer repeats its result beside the button.
- **Translate:** a long Live run no longer makes DazedTL use more memory with every request it saves; a run of a few thousand requests could take over a gigabyte while it ran.
- **Translate:** on a game with more than about a thousand maps, the variables step no longer rereads every map each second, which kept the app busy and slow.
- **GameUpdate:** a game translated into Japanese shows players its "Translation update available" message in Japanese; Set up writes the text into the update check's plugin settings, where it can be edited.
- **Images:** **Compare images** no longer names what discovery found an image to be twice, such as "Recommended" beside its state and again under Discovery.
- **Translate:** a stopped Batch that had nothing new to send for a file no longer kept Other event text open while every file read **Applied**, and the file's Lines show the run that translated it.
- **Set up:** while DazedTL saves a newly opened game's original files, a change that has to wait for them shows how far the save has got beside its button, with **Stop**, instead of a message to try again later.
- **Set up:** saving a newly opened game's original files is about five times faster when most of the game is images and audio, as in most games.
- **Set up:** **Change…** under Languages says at once that a game with work keeps its languages, instead of only after **Save languages**.
- **Project:** a recent game whose folder is gone, such as on a disconnected drive, now reads **Game folder unavailable** in the project menu and under Recent projects, not only once opened.
- **Footers:** a result that wraps beside its button, such as a two-line error, now ends right at the button instead of leaving a gap before it.

## [2.34.2] - 2026-10-26

### Fixed

- **Context:** **Save context** and **Copy starting prompt** still froze the app for minutes on a big game where an earlier save had been interrupted, for example by closing DazedTL while it saved; they now finish at once.
- **Context:** a failed **Save context** or other file write now names the file and why (for example that it is read-only), and a leftover Git lock says another Git process is using the game instead of "The operation could not finish."
- **Set up:** the first change DazedTL made to a big game whose version history wasn't set up yet froze the app for minutes while it saved the game's original files; it now saves them in the background as soon as you open the game, and a change that has to wait for them says so.

## [2.34.1] - 2026-10-26

### Fixed

- **Context:** after **Save context** failed while the game's version history was locked, every later save said "This guidance changed on disk" with no way past it but discarding the draft; the draft now saves once the lock is gone, including after a restart.
- **Context:** the first **Save context** or **Copy starting prompt** on a game whose version history was not set up yet could freeze the whole app for minutes on a big game, and closing it said saving was taking longer than expected; both now finish at once.

## [2.34.0] - 2026-10-26

### Added

- **Set up:** each game shows the languages it translates, such as English to Japanese, and **Change…** picks them until its first run; **Settings > Translation defaults** chooses the source language new games start with beside the target, and the app's labels, Images and the release playtest name the game's own languages. Games in the same script, such as English to Spanish, aren't supported yet.

### Fixed

- **Playtest tools:** a published patch of a game with Forge installed no longer stops players' game at start with "Failed to load" for the Forge plugin: installing Forge now saves its plugin file in the game's checkpoint with plugins.js, and a game already missing it gets it in DazedTL's next change to the game.
- **Translate:** a Chinese translation of a WOLF, KiriKiri or other game outside RPG Maker now wraps to its line width between characters, by the Chinese and Japanese line-break rules, instead of running past the window as one long line.
- **Images:** Chinese or Japanese text drawn into an image no longer shows as boxes when the chosen font lacks its letters: it is drawn in a Chinese or Japanese font the computer has.
- **Translate:** NScripter, KiriKiri and WOLF games no longer lose accented letters such as the ñ of "Señor": they are written without the accent, and a file holding a letter the game's Japanese text encoding can't write at all stops with a message naming the line instead of saving it with the letter missing.

## [2.33.2] - 2026-10-23

### Fixed

- **Project:** a game moved into a folder inside its old one, whose project then read "Project unavailable · Select an RPG Maker MV, MZ, Ace or WOLF game root", opens with its project again from its new folder or with **Find game folder**.

## [2.33.1] - 2026-10-23

### Fixed

- **Project:** a game moved or renamed, also into a folder inside its old one, now opens with its project and all its work instead of as a new project at Set up; while DazedTL can't find a project's game, the Project page offers **Find game folder**.
- **Forge:** quick save (Ctrl+S) in RPG Maker MZ games no longer says "Quick Save failed" after saving. Forge is updated to 1.4.0 with a redesigned Actors tab; click Install Forge again for a game that already has it.
- **Translate:** messages and choices made only of punctuation, such as `・・・・・。`, `.......。`, `？` or `「……」`, now show English punctuation (`.....`, `.......`, `?`, `"……"`) instead of keeping the Japanese marks and the trailing `。`.

## [2.33.0] - 2026-10-22

### Changed

- **Images:** investigating images now looks at each set of look-alike CG frames by what changes between them, so it uses far less of your assistant's plan.

## [2.32.1] - 2026-10-22

### Fixed

- **Settings:** Send to your phone no longer shows a code that Android cameras open as a Google search; type the Phone topic into the ntfy app on any phone instead.

## [2.32.0] - 2026-10-22

### Changed

- **Settings:** Send to your phone shows a code Android phones scan with the camera to connect ntfy, and new phone topics are a few everyday words that are easy to type on an iPhone.

## [2.31.0] - 2026-10-22

### Added

- **Settings:** Notifications can now send to your phone through the free ntfy app (Android and iPhone), so you hear when a Batch comes back, QA finishes or work waits for you while you are away from the computer.

### Changed

- **Line widths:** measured widths now keep a few characters spare on each line, and the measurement lists symbols such as ❤ that the game's font lacks, which other computers draw at another width; translation counts ❤ and similar symbols as full width.

## [2.30.0] - 2026-10-22

### Fixed

- **Checkpoints:** **Copy assets & finish** in the Game updates tool rebuilds a damaged record of a game update's assets from the release folder the update was applied from, as Guided does, and a record it cannot rebuild says to copy the assets yourself or go back to the checkpoint before the update.
- **VX Ace:** applying translated scripts no longer renames a script whose name holds characters such as `<>:"?`, so the editor shows the names you made and a later game update does not read Scripts.rvdata2 as changed.
- **Translate:** a Batch rerun that finds nothing new to send for a file no longer reads it Ready to apply, or counts the task done, when the file's earlier translation is not in the game yet; the file keeps the state the earlier run left.
- **Release:** right after a build, **Done** on the last saved ZIP reports it, instead of "Patch ZIP saved." beside the build button saying it again.

## [2.29.0] - 2026-10-22

### Added

- **Line widths:** unsaved width edits can be undone with **Discard draft**, as in Guidance.

### Fixed

- **Inspect run:** Lines left shows a line the model left in Japanese with its Japanese text (and its speaker) under Source text, instead of only the speaker or "-".
- **Line widths:** clearing a width field with select all and Backspace leaves it empty while you type, instead of showing "0" so that typing 44 reads "044".
- **Set up:** after you press Stop, setup now reads as stopped in a neutral note, not as red error text with "Prepare game files" marked Blocked.
- **Guided steps:** when a result beside a button, such as Save line widths, runs to two lines, the second line starts under the words instead of under the check mark.
- **Checkpoints:** **Copy assets & finish** no longer stops with "Pending asset update is invalid" after a game update's record of its assets was damaged, which left every game change refused.
- **Release:** after going back in Checkpoints to the files a patch ZIP was built from, Last saved patch ZIP no longer reads "Outdated · Game files changed since this build".
- **Inspect run:** an open Choose request list stays under its field when a row appears above the field, instead of staying put and covering it.
- **Translate:** a task no longer shows its done mark while files still read **Ready to apply**, such as after **Start over** or a new **Other event text** run, and **Other event text** no longer reads files only **Maps & events** translated as **Applied** with no lines.
- **Assistant-led:** the game folder notice looks like the one in Guided steps (an amber note, not a red banner), and a game update stopped partway says "A game update was interrupted. Finish the interrupted update, or cancel it, under Checkpoints to continue." instead of "unfinished Git cherry-pick".
- **Stop:** pressing Stop in Set up, Line widths, Cost estimate or Release now says what was kept and whether running it again continues or starts over, instead of "Completed writes were retained; review the destination before retrying."
- **Cost estimate:** after you stop an estimate, a note beside the button says it was stopped and nothing was saved, instead of the page quietly going back to Not started.
- **Translate:** after a game update, **Apply** is unavailable while a file it would apply reads **Outdated**, with "Reload changed files from the game first." beside it, instead of putting the old translation over the update's file.
- **Checkpoints:** a game update's review no longer lists `Forge_MZ.js` and `plugins.js` as the release's changes, and applying it no longer installs Forge into a game that didn't have it.
- **Translate:** **Other event text** offers **Apply** only for its own translated files, so before its first run it no longer shows a disabled **Apply (2)** with "Saved translations applied." for files **Maps & events** applied.
- **Plugin files:** after **Start over**, "Ready to apply" shows once, in the Assistant task header, not also on the Translated plugin text row; other assistant tasks no longer repeat their state on a row either.
- **Line widths:** after a text fit failed or was stopped, **Save line widths** fits the text again even with the widths unchanged, instead of doing nothing until a width changes.
- **Translate:** after a game update, one changed file reads "Reload it from the game", and "1 file reloaded from the game." goes away once you translate or apply.
- **Run history:** **Reapply** and **Apply translated output** are unavailable while a file they would write reads **Outdated**, with "Reload changed files from the game first." beside them, instead of failing after the click.
- **Translate:** while a file reads **Outdated**, the footer says "Reload changed files from the game first." instead of "Translate prepares an estimate for your approval."
- **Checkpoints:** after a game update, **Translate the new text** counts the lines each task still has to translate, in its summary and on each task, instead of repeating the update's count after you translated them.
- **Checkpoints:** the "Undone; 2 files changed." result stays beside the checkpoint the undo made, instead of moving to a later checkpoint such as **Install Forge**.

## [2.28.0] - 2026-10-22

### Fixed

- **History:** an Assistant-led game's History now lists its other activity, such as Start over, under Translation runs.
- **History:** Start over's row says how many files it put back instead of "0 files reloaded from the game".
- **Inspect run:** a Batch request's Response tab shows the Original and Translation table, as a Live one does, instead of the reply's raw JSON, and the request list is wide enough to read "Passed, 12 lines kept in Japanese" on one line.
- **Progress:** after changing a game from Guided steps to Assistant-led, Progress no longer says your assistant has started preparing the game before you have copied its prompt.
- **History:** Plugin files applies get a row under Other activity.
- **History:** the Database files and Maps & events applies are named for their task instead of both reading "Apply selected saved outputs", and History's Undo names the batch it undid.
- **Checkpoints:** after Go back or Undo, the result sits by the new top checkpoint; Save a copy's result no longer splits the folder's date and its Open folder link matches the message; the update header no longer reads "· complete" in lowercase.
- **Release:** the patch ZIP no longer carries the game repository's `.gitignore`, `.gitattributes` and `README.md` at its root.
- **Translate:** opening the Images tab no longer shifts the stage strip and task tabs sideways; only the image grid and preview use the full window width.
- **Footer:** a long running-operation message you expanded with **Show more** stays open as its progress changes, and a new error starts collapsed instead of opening like the last one.
- **Release:** on a VX Ace game, undoing or going back to a checkpoint no longer makes Release say "The game's data is older than ace_json" and hold Review & build patch ZIP until Pack outside edits; Data an assistant or another tool edited still waits for Pack outside edits.
- **Game updates:** previewing an update of a VX Ace game no longer says its translated data files are "replaced by official binary file" when the update packs them from the merged text, and it lists the release's `Game.rgss3a` as replacing the archive kept for patches.
- **Line widths:** going back to or undoing a checkpoint from before Save line widths now puts Line widths back to the widths the game uses again, instead of still showing the saved ones, so saving them again fits the text.
- **Game updates:** **Apply update** no longer flashes "Finish the interrupted update" with both buttons disabled while it runs; the preview and the Last saved patch ZIP card no longer repeat the same status two or three times.
- **Checkpoints:** after Go back, the checkpoints it took out read "Taken out".
- **Guidance:** saving after editing only Style & quirks names the checkpoint "Save Style & quirks" instead of also listing an untouched Game context; while a stopped game update holds the game folder, Save guidance and Save line widths are unavailable with "Resolve the game folder notice above first." only when they have something to save, instead of Save line widths failing after the click.
- **Guided steps:** clicking Stop beside Save line widths, Estimate cost, Set up or Build now reads "Stopping…" until the work stops, and says why if it could not stop.
- **Translate:** **Apply** on Maps & events now puts in the files' newest translations, including Other event text's saved output for the same files, instead of copying the earlier run's files again while saying "Saved translations applied." and leaving the files at **Ready to apply**; its review names the files that carry another task's translations, and only Run history's Reapply says "Reapplying makes no API requests."
- **Assistant-led:** after **Start over** put the original game back, Guided steps no longer read Database files, Maps & events and Plugin files as **Applied**; their saved translations read **Ready to apply** until applied again.
- **Text QA:** on a VX Ace game, Pack outside edits no longer flashes in the Text QA header right after Apply corrections.
- **Translate:** a line left in Japanese, such as one the model gave back unchanged, reads "still in Japanese" in a file's status and Inspect's **Lines left** instead of "never translated", which was wrong once the line had been sent.
- **Translate:** a VX Ace game that still reads its `Game.rgss3a` no longer lists its files as **Applied**; they read **Ready to apply**, **Apply** says to convert Ace data in Set up first, and the notice no longer names an Assistant-led operation or sits beside Set up's own messages.
- **Translate:** at narrow widths the footer's count no longer wraps onto a second line; "Saved translations applied." goes once a later run leaves files to apply; the **Lines** heading matches the others; and **Needs review** has its own mark instead of the eye of the row's Inspect button.
- **Translate:** a game opened with its maps already translated, such as a copy of a translated game, no longer counts each map one line short in **Lines**, or reads a map whose only text is its name as **Done**.
- **Game updates:** after an update changes a file you translated, such as a character profile it rewrote, Database files and Maps & events read the file **Outdated** until **Reload from game**, instead of **Applied** with the new text left in Japanese.
- **Game updates:** a VX Ace update that is only a new `Game.rgss3a` is converted as Set up converts the game when you bring it in, instead of saying "This engine needs assistant preparation"; applying it keeps your translation and the game's other files.

## [2.27.2] - 2026-10-22

### Fixed

- **Translate:** a line whose translation keeps a single kana or mark from the Japanese, such as the 〇 of a censored word or a kaomoji's ﾉ, no longer leaves its file at **Needs review** with "1 line never translated. Translate sends it" while the next Batch finds "No new translation requests"; such lines now count as translated, and a line the model gives back unchanged is still sent again.

## [2.27.1] - 2026-10-22

### Fixed

- **VX Ace:** once anything was applied, Release builds the patch ZIP again instead of refusing with "Supply unique source and guidance file paths.", and the patch leaves out the `ace_json` folder; a game update keeps your translation instead of putting the new version's Japanese back, and a new version that comes with `Game.rgss3a` is converted as Set up converts the game instead of waiting for an assistant.
- **Translate:** a kaomoji with half-width marks, such as (ﾟдﾟ), no longer comes back with its eyes stacked on the mouth or as a box, and a short line such as え？ that the model gives back untranslated is no longer saved as translated; it keeps its original text and the next Translate sends it again.

## [2.27.0] - 2026-10-21

### Changed

- **Project page:** a new **Checkpoints** tab lists every change DazedTL made to the game by version and stage, shows what each changed line by line, and can go back to one, undo one or save a copy of the game as it was then; it replaces the **Versions** tab, whose game updates now start here, and the **Backups** tab; to get an old state of the game, use **Save a copy…** on a checkpoint.
- **Translation:** DazedTL saves every change it makes to the game, such as an Apply, a Plugin files change, Line widths or Text QA's corrections, as its own checkpoint in the game's Git history, and saves edits you make outside DazedTL as a checkpoint of their own, so **Review translation checkpoint**, **Save translation version**, **Save version** and **Not committed yet** are gone.
- **Assistant-led:** DazedTL saves your assistant's changes to the game as checkpoints itself, one each time it reports a phase and one when a translation run ends, so your assistant no longer saves them.
- **Guided:** one **Save guidance** click saves as one checkpoint naming the documents it saved.
- **History and Plugin files:** **Undo** takes out a batch of QA corrections, playtest fixes or rewrapping, or a Plugin files application under **Recovery**, in one click by undoing its checkpoint, instead of a reviewed restore from copies DazedTL saved; it then reads **Undone**, and undoing it again from **Checkpoints** reads **Redid**. Batches applied earlier keep **Review restore**.
- **Images:** **Restore originals…** puts the original images back from the game's Git history, so preparing an image no longer saves a copy of it.
- **Assistant-led:** **Start over** puts the original game back as a new checkpoint, so the earlier attempt stays under **Checkpoints** instead of its Git history moving to `.dazedtl/archived`.
- **Set up:** DazedTL keeps a copy of the original game files in the game folder's Git history before its first change, kept privately and never pushed with your translation, and takes no more backups, so **Back up the original** is gone. Games set up earlier keep using their backups, which stay in the game's `.dazedtl/backups` folder; the user guide's **Backups from before checkpoints** explains how to restore them.
- **Translate:** cost estimates made before updating read as outdated once and need estimating again; runs you already approved or sent keep going.

### Fixed

- **Translate:** a reply with one line still in Japanese no longer throws away the whole request: only that line keeps its original text, **Inspect** names it, and the next Translate sends it again; a kaomoji such as (ﾟдﾟ) the model keeps from the source no longer counts as Japanese.
- **Images:** **Restore originals…** now says when it is done, and an image it put back reads **Needs review** with what to do instead of "No image in your list is translated yet."
- **Release:** building the patch ZIP after a game update no longer fails with "The untranslated source baseline changed. Prepare a new request plan for this game version."
- **Text QA:** undoing QA corrections after applying Plugin files no longer leaves Text QA reading **Outdated** with the corrections hidden; it offers them again.
- **History:** **Other activity** stays open when you come back, and **Status** counts a Plugin files apply as the last activity.

## [2.26.0] - 2026-10-21

### Added

- **Line widths:** after you save new widths, text that still does not fit even rewrapped, such as help that needs more rows than its window shows, is listed under **Too long to fit** with its file and place, and saving a Dialogue narrower than With portrait says that With portrait was lowered to match.

### Changed

- **Translation versions:** each translation version now commits the game's glossary, settings and skills (`.dazedtl/glossary.txt`, `.dazedtl/settings.json` and `.dazedtl/skills/*.md`), so they are in the game's Git history and pushed to its repository with the translation; before, the patch rules hid them from Git, and a Guided game's glossary was in no backup. Players never get them: the game's `.gitattributes` now keeps `.dazedtl` out of the downloads GameUpdate applies and out of patch ZIPs. A game set up before gets both with its next translation version.
- **Context:** cost estimates made before this update read outdated once and refresh on the next estimate, because Maps & events now sends less; runs already approved or sent carry on as they were.

### Fixed

- **Versions:** an action that has just started now says **Running** once, not **Running Starting…**, and after **Cancel update** the Compare step no longer shows **Last run: complete** from a comparison that no longer applies.
- **Maps & events:** the names, nicknames and profiles events give characters (Change Name, Change Nickname and Change Profile) are now translated and counted in **Lines**, like the database's own; before, they stayed in Japanese unless **Event text sources** turned them on, while the file read done. In a project translated before, each file holding them now counts them as lines left, and **Translate** sends only them.
- **Assistant-led:** your assistant's first preparation of a VX Ace game now converts its data, unpacking an encrypted `Game.rgss3a` and moving it into `.dazedtl/ace` as Guided's **Convert Ace data** does; before, preparation stopped until the data was converted with tools Assistant-led doesn't have, and a game whose archive still sat beside `Game.exe` refused every write with advice to use Set up, which Assistant-led doesn't have.
- **Assistant-led:** in a VX Ace game, the text your assistant writes, and the text refitted when it saves Line widths, is now packed into the `Data` files the game reads, so playing the game folder shows the translation; before, the game kept showing the Japanese.
- **Set up:** in a VX Ace game, formatting the game data now packs it into `Data`, so **Release** no longer asks for **Pack outside edits** afterwards.
- **Game updates:** GameUpdate's settings are no longer written while a game update is stopped on a conflict, which left **Versions** unable to cancel the update; the same goes for the **Speaker slips** your assistant fixes and for preparing the game in **Set up**.
- **Game updates:** while a game update is stopped on a conflict, nothing else DazedTL does writes the game's tracked files either, so **Versions** can still cancel it: saving the glossary or other guidance, your assistant's preparation, installing or removing the playtest tools, preparing images and reference games now say the update must be finished or cancelled first, and names paid for in a declined Batch are added to the glossary once it is.
- **Game updates:** **Cancel update & restore translation** now puts the game back at the version it had before the update, so **Versions** shows that version again, **Preview changes** compares the release again and the glossary and other writes work; before, Versions kept the new version, read "Assets to recover" with nothing to do about it, and every write to the game said the update had not finished restoring game assets.
- **Game updates:** an update that stopped with its game assets still to copy no longer leaves **Versions** reading "Assets to recover" with nothing to do while every write to the game refuses: **Copy assets & finish** copies them when the translation already has the update, and **Cancel update** puts the game back at the version before it otherwise. An apply that fails without a conflict now leaves the game as it was.
- **Game updates:** while a game update is stopped on a conflict, **Versions** can cancel or finish it with unsaved **Guidance** edits, which stay drafts to save afterwards, and **Save guidance** is unavailable until then; before, Cancel refused until the edits were discarded.
- **Translation versions:** a skill whose name ends in upper-case `.MD`, such as `.dazedtl/skills/Style.MD`, is now saved with the translation like any other; before, on Windows, the next translation version refused with "Nested or global ignore rules conflict with the exact patch file list".
- **Guidance:** when saving guidance fails, only the tabs you edited read **Draft**; before, **Style & quirks** and **Game context** read Draft too when their files didn't exist yet.
- **Footer:** an error or result beside a button at the bottom of a page no longer pushes the other buttons to the far left, as Cancel's error did under **Versions**.
- **Maps & events:** text that is already finished is no longer sent again on every run: a line the game wrote in English inside 【】, whose translation replaced the game's own English, a translated message whose only Japanese is inside a plugin code such as `\SA[...]`, map names and event labels from map notes; those labels (`<LB>`, `<LB:...>`, `<namePop:...>`, `<dn:...>`) now count in **Lines**, so a map no longer reads done with them still in Japanese.
- **Maps & events:** an event label from a map note (`<LB:...>`, `<namePop:...>`, `<dn:...>`) now translates only the label and leaves the note's other tags alone: `<dn:古びた井戸><Shadow:false>` no longer loses `<Shadow:false>`, and `<dn:井戸><Sound:井戸>` keeps its sound name.
- **Line widths:** saving wider widths now joins again the lines DazedTL broke to fit narrower ones, in messages and choice help, so help that needed more rows than its window at a narrow Dialogue leaves **Too long to fit** once the window is wide enough; before, the narrow line breaks stayed.
- **Line widths:** saving wider widths now also lays out again a long message DazedTL split over several windows at a narrower Dialogue, and **Apply** lays out text translated while the widths were narrower to the widths the game has, so neither keeps its narrow lines and pages; the notice now reads "Fitted 3 lines to the new Line widths.", since a wider fit joins lines as well.
- **Assistant-led:** after you save wider Line widths, text your assistant writes into the game is laid out for them, even from a copy it took before; before, writing that copy put the narrow lines back.
- **Line widths:** after you save new widths, **Save line widths** shows the text being fitted to them until that is done; before, it already said "Line widths saved." with a check mark while the fit ran.
- **Line widths:** while text is fitted to new widths, the **Running / Starting… / Stop operation** row above the page no longer pushes the page down about 55 px; **Stop** sits beside **Save line widths** instead.
- **Footer results:** a result beside a footer button that wraps to two lines, such as a notice or an operation that failed, no longer makes the footer taller or moves its buttons to a second row, and a long one shows its first two lines with **Show more**, at any window width.
- **Translate:** at the narrowest window the footer on Maps & events and the other file tabs stays one row tall, with its guidance line shortened (hover it for all of it), instead of wrapping to a second row.
- **Line widths:** choice help translated in pieces around the game's own page number, such as "(1/3)", is now listed as not fitting when all of it needs more rows than the message window shows; before, each piece was checked alone and the cut-off rows went unreported.
- **Text QA:** choice help translated in pieces around the game's own page number, such as "(1/3)", now goes to its reviewers to shorten when all of it needs more rows than the message window shows, and a correction that would make it too tall as a whole is refused; before, each piece was checked alone.
- **Text QA:** a translated line whose only Japanese is inside a plugin code such as `\SA[...]` no longer reads as Japanese left in the text or as never translated, matching **Lines**.
- **Translate:** a game variable translated while several files translate at once keeps its translation everywhere it appears; before, one file could drop the names another had just translated, so the same variable could come out two ways.
- **Translate:** on Windows, a Batch cost estimate or run no longer stops with "Permission denied" on `job.json` when it reads its saved run while that run is being saved, which left **Submit Batch** unavailable.
- **Translate:** once every saved translation is in the game, **Apply** is disabled with "Saved translations applied." beside it, and Translate on finished files shows "No new translation requests" in a small dialog instead of a tall, mostly empty one.
- **Translate:** an estimate or start that fails now shows its message in a small dialog that fits it, like the no-requests result, instead of a tall, mostly empty one.
- **History:** a run's first **Apply** from Translate is listed as "Apply selected saved outputs" instead of "Reapply saved run output", which now names only applying a run's saved output again.
- **Release:** a VX Ace game whose folder is named in Japanese now opens Release with a clean game ZIP name it can build, the folder name in English letters or `translated-game.zip`, instead of a rejected Japanese one; while a name is rejected, **View files & exclusions** says why beside it.

## [2.25.0] - 2026-10-20

### Changed

- **Database files and Maps & events:** **Lines** and each file's status now come from the file itself, so they show before the first run (such as 0 / 240), stay right after reruns and **Reload from game**, and a task reads done only when no Japanese is left; hover a **Needs review** status to see why, and click a file's eye to list its lines left.

### Fixed

- **VX Ace:** translations now show in the game right after **Apply**, as do Plugin files, Text QA, Line widths and restores in History, instead of waiting for a separate packing step; a game that came with `ace_json` already converted and `Game.rgss3a` still beside `Game.exe` now has Set up set the archive aside, keeping its translations, instead of releasing the untranslated game.
- **Context:** updating DazedTL no longer makes the whole-game **Cost estimate** read outdated; one made with 2.13.2 to 2.24.0 stays current while the game and settings are unchanged.
- **Images:** **Apply** on an image whose edited copy was saved without preparing it now says "Prepare this image first so its original is kept" instead of failing with "Nothing was applied - The operation could not finish."
- **Maps & events:** a message or scrolling text the translation leaves untranslated or declines now keeps every row as the game has it, instead of being joined into one row, as does one an older run saved a refusal note for, so its event keeps its place for saved games.
- **Maps & events:** in a project translated before **Comment text** came on, choice help still in Japanese now counts as lines left instead of the file looking finished; **Translate** sends only the help.
- **Database files and Maps & events:** after a rerun that sent only some lines, such as choice help, **Lines** and the project's lines translated no longer drop to that rerun's own lines (for example 2 / 2 instead of 11 / 11).
- **Maps & events:** when several maps repeat the same scene, a Batch still sends it once, and now each of those maps counts its lines and shows which request failed validation, instead of "validation mismatches were recorded, but this older run did not retain which request failed".
- **Text QA:** updating DazedTL no longer makes finished QA read Outdated with "An update changed QA's rules after this task was prepared", so its corrections apply, Undo and Apply again keep working, and QA in progress, including QA started with 2.23.0 to 2.24.0, goes on where it stopped instead of reviewing again.
- **Maps & events:** translated choice help now keeps the game's own event commands and its own help rows, so translating it again no longer deletes or fills rows such as "(1/3)" or a blank spacer, and saved games stay at their place in the event.
- **Maps & events:** choice help shown beside a portrait now wraps to the portrait's width as it is translated, and its list items keep a row each.
- **Maps & events:** choice help markers listed by a plugin are now found in a plugin list without a semicolon or with code after it, by translation and Text QA alike.
- **Assistant-led:** choice help the assistant translates is now fitted to the game's Line widths like its other text.
- **Text QA:** the playtest now matches an untranslated message it sees with the line it lists as never translated, and a message whose speaker name alone was translated counts as never translated.
- **Text QA:** an applied correction now colors only the words it changed, instead of the whole new line, so an unchanged second row no longer looks changed.
- **Playtest:** a placeholder glyph such as ◯ that the message window draws is now reported once per message, instead of once for the whole run.
- **Maps & events:** translated scrolling text now lays its lines over its own rows instead of adding a row per line, so translating it again no longer changes its event and saved games stay at their place.
- **Text QA:** a correction that makes choice help shorter, or fitting it to narrower Line widths, no longer leaves an empty line above the game's own rows such as "(1/3)".
- **Assistant-led:** fitting choice help to Line widths now keeps a row the assistant left as the game wrote it, such as "(1/3)", on its own line instead of running it into the text around it.
- **Text QA:** a line you answer **Keep current text** for now stays settled: once QA's corrections apply, the playtest's problem on it reads "Text QA reviewed it" instead of waiting for QA's next round, and the next round no longer asks about it again, including for answers given in 2.24.0.

## [2.24.0] - 2026-10-20

### Fixed

- **Text QA:** once QA is prepared again, the assistant can no longer go on with the task it replaced, which had reported a new round as finished while nobody reviewed it.
- **Text QA:** a choice reviewers settled in an earlier QA of the game, such as "Demon Lord", carries into later rounds, which no longer raise the same glossary fixes again.
- **Text QA:** a line the playtest still flags because its correction never reached the game, such as a weapon description cut off in its help window, comes back in the next round instead of reading as reviewed.
- **Fitting:** a message's list keeps one item a row when an item needs a second row, instead of running two items together, which Text QA's own check then flagged.
- **Playtest:** Japanese that another window draws while a message is open, such as a choice's help or a map HUD, is no longer reported as the message's line for Text QA, where it read "Not in QA's review"; text that was never translated is sent to translation instead, and a choice's help points to **Maps & events** with **Comment text** on.
- **Maps & events:** the help a choice shows from event comments, such as MPP_ChoiceEX's 選択肢ヘルプ, is now translated: Guided turns **Comment text** on for games that show it, projects you already have included, and each help line wraps to the message window instead of running past its edge.
- **Maps & events:** choice help shown beside a portrait wraps to the **With portrait** width, and Apply, new Line widths and Text QA corrections rewrap translated help that no longer fits, keeping its event commands.
- **Text QA:** the playtest shows each choice's help before choosing, and reports help too tall for the message window, whose first rows players never see.
- **Text QA:** the never-translated report and the playtest list choice help that was never translated everywhere in the game, not only where the playtest happened to see it, and no longer list the plugin setting naming these comments as text to translate.

## [2.23.1] - 2026-10-20

### Changed

- **Text QA:** each correction and question says what is wrong in one short, plain sentence; the reviewers' full reasoning moved to the History inspector, where QA's record also lists lines a reviewer found wrong but could not correct.
- **Text QA:** a question always offers the reviewer's proposal beside **Keep current text**; a problem no correction can fix is reported as not corrected instead of a question you could only keep, and never holds up applying the rest.

### Fixed

- **Text QA:** corrections to centered or instant-text messages that need an extra row are no longer refused, which had left lines such as a two-line event banner for you to fix by hand.
- **Text QA:** a name reviewers settled, such as "Demon Lord", no longer fights a glossary entry that says otherwise through round after round of review, ending as unverified.
- **Text QA:** two lines from one long scene go to one reviewer, so the scene is read once, lowering the cost on games with very long events.
- **Playtest:** a font change such as `\fn[和風]` no longer counts as Japanese left in translated text.
- **Playtest:** plugin strings **Plugin files** already settled, such as notetag names, are no longer reported again, which reopened the Plugin files task for nothing.
- **Playtest:** a battle window sized tightly to its text, such as Keke_PredictionSystem's action preview, no longer reads as text running past its bottom edge.
- **Playtest:** fixes written into the game are saved as a version of their own instead of riding along with the next Text QA apply, and the status says when the game runs other fixes than the ones you are editing.

## [2.23.0] - 2026-10-19

### Added

- **Text QA:** your assistant can now fix crashes and windows too small for English that the playtest finds, in a fixes plugin of DazedTL's own; DazedTL puts it into the game only once a play of the game with it in place breaks nothing new, translation versions and patches always carry it, a game update that changes `js/main.js` keeps loading it, and **History** on the Project page takes it out again with **Review restore**.
- **Plugin files:** plugin text your assistant kept in Japanese goes back to it once to decide again when the playtest saw it on screen, with where it showed.
- **Plugin files:** VX Ace games get the task too: your assistant translates the text the game's scripts show, such as menu commands and battle messages, and Ace packing writes the applied scripts back into the game.
- **Assistant-led:** your assistant saves the **Line widths** it measures in the running game, VX Ace windows included, and DazedTL fits the text it writes to them, and what it already wrote when it saves new widths, without adding commands to the game's events, so saved games still load.
- **Assistant-led:** your assistant shortens plugin text that Text QA's screen captures show squeezed or cut off, such as a menu command, as **Plugin files** does in Guided steps.

### Changed

- **Text QA:** for MV and MZ games the Text QA task is now also the final check: your assistant plays the game while QA reviews it, fixes what the playtest finds and plays it again after QA's corrections, so you copy one task instead of running the playtest yourself; the separate **Playtest** task is gone, and its panel shows under Text QA's. For a game whose Text QA finished before this version, **Run QA again** has your assistant play it.
- **Text QA:** for MV and MZ games, **Assistant tasks** shows Text QA as **Waiting** until a playtest of the game as it now is leaves nothing more for your assistant, and only then does the Project page mark it done; a plugin change during QA, such as one of your assistant's fixes, reads **Waiting** instead of **Outdated**.
- **Text QA:** QA reviews only text it hasn't reviewed before or that changed since, including lines whose glossary entry changed, so running it again after an update or a few edits reviews just those, and the page says so, such as "17 lines checked · 799 unchanged since earlier QA"; tell your assistant which version was checked before you used DazedTL, and QA skips that text from then on. Its reviewers also need far fewer turns, so QA uses less of your assistant's plan.
- **Text QA:** the page shows only QA's progress, the questions it can't settle and its corrections; **Review them** and its lists are gone, and what QA did not cover, such as lines its reviewers declined and Japanese never translated, is in **History** on the Project page when you inspect **Prepare or resume translation QA**.
- **Text QA:** text the game squeezes only after QA finished goes to a follow-up round of review instead of a **Squeezed after QA** list.
- **Playtest:** places your assistant adds, such as a recollection room, are kept, and every later playtest visits them.
- **Assistant-led:** your assistant fixes crashes and windows too small for English that the playtest finds in the same fixes plugin instead of editing the game's code; DazedTL puts each fix into the game only once a play of the game with it in place breaks nothing new, then saves it as a version, so the patch always carries it.
- **Assistant-led:** your assistant keeps plot spoilers out of the messages it saves translation versions with, which players can read in the patch repository.

### Removed

- **Glossary check:** the Check task is gone; Text QA now puts the glossary's English into lines that write a term another way, such as a place name translated before its glossary row existed, and lists those corrections as **Glossary term**. Glossary fixes you applied earlier still restore from **History**.
- **Line width check:** the Check task is gone, as translation, **Apply** and Text QA now fit text to the **Line widths** themselves: they wrap like the Japanese where the English allows, count full-width marks such as ～ and ♥ as two characters, fit English beside a note tag left in Japanese, and leave the game's own scripts that build text, such as a score line, as they are, where the Line width check's rewrap could stop the game with "SyntaxError". Saving new widths after you apply rewraps the text DazedTL applied that no longer fits, which **History** restores with **Review restore**, and text a window cuts off even rewrapped goes to Text QA's reviewers to shorten.

### Fixed

- **History:** **Review restore** for QA corrections no longer stops at "Restore the newer text batch first." when a later batch, such as an **Apply** of other files, can't be restored; a batch restores once no later batch changed its files, and otherwise the button names the later batch to restore first, or says a later Apply replaced those files.
- **Plugin files:** **Apply to game** and **Review restore** now wait while a game update is stopped on conflicts, saying "The game folder has an unfinished Git cherry-pick. Finish or cancel it under Versions, or in Git, to continue." as **Apply** does; they wrote the game, after which **Cancel update & restore translation** failed with "error: Entry 'js/plugins.js' not uptodate". **Images** waits the same way.
- **Project:** the **Status** tab of an Assistant-led game shows its latest activity once, in the status card, instead of repeating it below as "Last activity", and building a clean game ZIP reads **Build clean game ZIP** in **History**, as on the Release page, instead of "Build public release ZIP".
- **Text QA:** running QA again, such as after a plugin change, continues the same review instead of starting a new one when the playtest found something, also once the review is finished; lines a later playtest finds are reviewed on their own.
- **Text QA:** a correction of a slip found in several lines, such as a quoted title that no longer matches, no longer gives as its reason the note its reviewer wrote on why some of those lines stay as they are.
- **Translate:** text an MV or MZ game keeps in a text variable no longer stops the game with "SyntaxError" when its translation holds a backtick, "${" in it shows as written, and a name code such as `\n[1]` or `\nc<Alice>` in it is kept; Text QA writes its corrections there the same way, wrapped to the list width in **Line widths**.
- **Text QA:** a correction that drops a name window code such as `\nc<Alice>` is refused, and a translated line that lost one goes to QA's reviewers.
- **Text QA:** a review left underway in the previous version keeps the read-through it had finished when your assistant picks it up after the update, instead of reading all that text again, also in games with text variables or name windows such as `\n<Alice>` and when its reviewers declined some lines.
- **Playtest:** **Problems** says where each text problem stands with Text QA: a line QA can't take reads "Not in QA's review" instead of "Text QA corrects it when QA runs again" forever, and a line QA corrected that the playtest still flags, or that QA reviewed only for another reason, goes to QA's next round instead of reading "Text QA reviewed it".
- **Playtest:** a place your assistant added that the playtest could not play no longer shows as "A script failed" in the game's code; it is listed with what the playtest did not reach.
- **Playtest:** item and skill descriptions longer than two lines no longer go to Text QA as cut off unless the playtest saw them cut off, as in games whose help window shows three lines or draws its own text; text a plugin adds beside a description, such as a line of stats, no longer counts as the description's.
- **Playtest:** in MZ games that use MessageWindowPopup, the layout check your assistant runs to measure **Line widths** and the playtest's message checks no longer fail with "Cannot read properties of undefined (reading 'rtl')".
- **Assistant-led:** patches always carry the update check and Forge plugins and the GameUpdate files Set up installs; a patch whose file list left them out made players' game stop at start with "Failed to load".
- **Assistant-led:** saving a translation version now stops and names the plugin when the patch's plugin list loads one that neither the patch nor players' game has, such as a plugin your assistant wrote, instead of making a patch that stops their game at start.
- **Assistant-led:** messages above the page, such as a warning or a failed action, line up with the panels below instead of sticking out past their right edge, as do error messages in **Settings** and above any page; a failed **Run playtest again** or **Estimate again** shows its error only beside the button.
- **Translation:** a game whose folder was moved or whose drive is disconnected says "Game folder unavailable. Reconnect the drive or open the game in its new location." as the Project page does, instead of asking you to open the Translation workspace in Guided steps.
- **Backups:** progress counts one file as "1 file" instead of "1 files", as when Start over puts back its first file.
- **Windows:** scripts your assistant writes over game text no longer crash with a 'charmap' UnicodeEncodeError: every copied task tells it to run them with DazedTL's own Python.
- **Release:** a VX Ace game in a clean game ZIP no longer stops on English Windows with "RGSS301.dll File corrupted" when its folder had a Japanese name: the game's folder inside every clean game ZIP now takes the archive's name, without `.zip`, instead of the game folder's, and Release asks for a VX Ace game's ZIP name in English letters.
- **VX Ace:** **Database files** no longer fails with "KeyError: 0".
- **VX Ace:** **Images** finds the game's images in `Graphics` instead of asking you to choose a folder.
- **VX Ace:** your assistant's **Event text sources** findings are no longer refused once the game is translated.
- **VX Ace:** a patch ZIP with translated images in `Graphics` no longer fails to build.
- **VX Ace:** the packed game no longer freezes at an event that sets a text variable, also in a game translated with an earlier version: **Release** asks each VX Ace game to pack again with **Review native Ace packing**, which writes the text variables an earlier version translated so the game reads them.
- **VX Ace:** the packed game's window shows the translated title instead of the Japanese one; packing puts it into `Game.ini` in plain letters.
- **VX Ace:** games start with their own windows' widths, 52 characters and 40 beside a face, instead of MV and MZ's 60 and 50, which ran past the window's edge; a Guided Ace game still on the old widths switches when you open it, and the text you applied is fitted to them.
- **VX Ace:** translated map names now reach the packed game.

## [2.22.0] - 2026-10-15

### Added

- **Plugin files:** your assistant now checks each plugin label it shortens in the game itself: DazedTL plays the game in a hidden window with the shorter text, without changing the game, and a label counts as shortened only once it fits on its screen, so a shorter label that is still squeezed, or that the game draws from another setting, goes back to your assistant.

### Changed

- **Text QA:** running QA again after plugin files change opens the game's screens again and keeps the review done so far, so labels **Plugin files** shortened drop off **Review them** and labels still too long go back to it; game text the game squeezes only now goes to review, or once QA has finished, **Review them** lists it under **Squeezed after QA**.

### Fixed

- **Text QA:** **Review them** keeps **Never translated** up to date when you run QA again after plugin text changes, or when **Plugin files** decides to keep a setting in Japanese, instead of showing the list from when QA was first prepared.
- **Plugin files:** a plugin label Text QA finds too long no longer shows "In no plugin file" after a plugin file you applied earlier changed outside DazedTL, such as by a game update, while Plugin files read as complete.

## [2.21.0] - 2026-10-15

### Added

- **Glossary check:** a new Check task lists translated lines whose English doesn't use the glossary's English for a term in their Japanese, such as a place name translated before its glossary row existed; choose **Use proposal**, **Keep text** or **Write a fix** for each line or a whole term, then **Apply fixes**, which History on the Project page can restore.
- **Plugin files:** plugin labels Text QA finds too long for the screen, such as a menu command, now go to Plugin files: copy the task again and your assistant shortens each one or keeps it with its reason, then click **Apply to game**; Text QA's **Review them** shows where each label stands, with **Open Plugin files**.

### Changed

- **Set up:** your assistant measures the note width on the windows that show the notes DazedTL wraps, such as item detail notes, instead of the narrowest note window in the game, so wrapped notes no longer come out narrower than their window.

### Fixed

- **Translate:** translating an RPG Maker MV/MZ game's database keeps the line breaks in descriptions, profiles and detail notes; it ran each into one line and rewrapped it, so separate lines, such as a weapon's Weapon Skill line, ran into the text and blank rows between notes disappeared. **Line width check** and Text QA corrections keep those line breaks too.
- **Text QA:** **Review them** no longer lists plugin settings that Plugin files kept in Japanese on purpose, such as names a plugin looks up or text players never see, under **Never translated**, and **Playtest** no longer reports them as Japanese left in the game.

## [2.20.1] - 2026-10-15

### Fixed

- **Translate:** translating an RPG Maker MV/MZ or SRPG Studio game's database again after a game update no longer replaces the game glossary's database sections, such as Items, Skills and Weapons, with only the names it just translated; the other rows stay, and a name translated again takes its new translation.
- **Translate:** adding translated names to a glossary section no longer drops a row that has a note after its translation, such as a character's voice notes in Game Characters.

## [2.20.0] - 2026-10-15

### Added

- **Images:** a scan groups images that share one backdrop and differ only in their text, such as name cards or area banners, and the task your assistant gets names each image's group, so your assistant rebuilds the clean backdrop from the other images instead of painting over the old text.
- **Images:** your assistant can take the font, size, outline, shadow and glow from an image you already accepted and draw the rest of its group in the same style.
- **Image Text Editor:** text boxes have **Outline**, **Shadow** and **Glow** settings, each with its own colour, and the font list shows the game's own fonts under **This game**.
- **Image Text Editor:** **Rebuild from surroundings** offers a **Repair method**: **Harmonic (smoothest)**, now the default, **Telea (fast)** or **Navier-Stokes (follows lines)**.

### Changed

- **Images:** an image your assistant edits reads **Ready to apply** only after your assistant saves how to redraw it and the image passes the app's checks; otherwise it shows **Needs review** with the reason, such as "No reusable recipe is saved for this image.", and **Apply to game** leaves it out until it is fixed or you choose **Mark user reviewed**.
- **Images:** edited images keep the original file's colour profile and other embedded details when they are saved and applied.
- **Plugin files:** **Apply to game** writes the translated plugins in one click instead of opening a list of file names first; **Recovery** still restores them.
- **Text QA:** your assistant runs four reviewers at the same time instead of reviewing all the text itself, so QA finishes several times sooner; the time left follows how fast it really goes, and the activity line says **one reviewer at a time** when your assistant reviews alone.

### Fixed

- **Images:** an image investigation your assistant has saved only part of no longer reads finished and plays the notification while your assistant is still looking at the other images.
- **Images:** on Windows, the LaMa and AOT repair models can be downloaded and installed; downloads no longer fail with `CERTIFICATE_VERIFY_FAILED`, and when Windows lacks the Microsoft Visual C++ Redistributable your assistant can install Microsoft's own package.
- **Translate:** **Apply** on a task applies that task's own finished run; it could put another task's last saved translations into the game instead.
- **Text QA:** after the app updates while it is running, **Run QA again** no longer keeps saying "An update changed QA's rules after this task was prepared."
- **Player walkthrough:** an RPG Maker MV/MZ walkthrough no longer reads finished and plays the notification as soon as your assistant first saves `WALKTHROUGH.html`; it waits until your assistant's validation of the last saved page passes, and Release says when the page is saved but not validated yet or validation found errors.

## [2.19.0] - 2026-10-15

### Added

- **History:** **Inspect** beside each request error opens that request, and **Inspect run** finds a request by number, file, state or error text instead of paging with **Next**; the request shows its error above its lines.

### Fixed

- **Inspect:** after choosing a request, typing in the request box starts a new search instead of adding to the chosen request's name.

## [2.18.0] - 2026-10-14

### Changed

- **Images:** the **To translate** view is now **Recommended**, and images applied to the game leave it and **Unsure** for **Applied**.

## [2.17.0] - 2026-10-14

### Added

- **Images:** **More > Investigate all images again** has your assistant investigate the images again from the start. Its recommendations replace your list of images to translate, except images already translated.

### Fixed

- **Images:** **More** no longer offers to investigate images "not examined" when your assistant had set them aside; the task stopped with "Every image has been investigated."

## [2.16.0] - 2026-10-14

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
- **Images:** scrolling the image grid, filtering, resizing thumbnails or previewing an image no longer shows "Saving choices…" and holds **Apply to game** and **Copy translation task** until the save finishes; only a change to the images to translate does. **Retry saving choices** after a failed save keeps images ticked since then, such as by your assistant, instead of saving the older list over them.
- **Translate:** a Batch of **Maps & events** no longer sends a map's name again when an earlier run already translated it but did not finish that map, such as a Live run that failed partway; the name was sent and charged a second time.
- **Assistant-led:** approving an API estimate no longer freezes the app while every request is checked again; the run checks them itself before it sends anything. On a large game this could hold the whole app for over 30 seconds on Windows, and organizing and estimating also look up fewer files.
- **Assistant-led:** saving each request your assistant translates no longer checks every other request of the run again or rewrites the progress counts of every line. On a 900-request run each save took about 2.5 seconds on Windows and held the app for nearly as long; it now takes about 0.6 seconds and holds the app for under half a second. The first save after updating converts the saved progress once.

## [2.15.1] - 2026-10-13

### Changed

- **Translate:** translating a file again after an earlier run translated part of it sends the remaining lines together, up to 50 per request, instead of one request for each gap between lines already translated. Large common events could become hundreds of requests of a few lines each, every one paying for the full instructions: one game's CommonEvents went from 415 requests to 142, with 57% fewer input tokens.

## [2.15.0] - 2026-10-13

### Added

- **Settings:** Kimi (platform.kimi.ai) is a new provider. Kimi K2.6 and K2.7 Code can translate in a Batch at 40% off the Live price; Kimi K3 translates Live.

### Fixed

- **Translate:** a line that comes back as a refusal note, such as "[Not translated: …]", "[Omitted]" or "Translation declined.", now counts as a refusal. The request is asked again once with the context clarification; if the model still declines, its lines keep their original text and the file reads **Needs review**. These notes used to be saved as the translation.
- **Translate:** after stopping a Live run that translated several files at once (**Concurrent files** above 1 in settings carried over from an earlier version), every finished file counts as saved. Some used to read as not saved and were translated again.
- **Plugin files:** games whose plugin list repeats a plugin, such as an empty divider plugin listed many times, no longer stop **Copy plugin task** with "Duplicate configured plugins need investigation before exact scope can be formed."
- **Translate:** Batch cost estimates for large games finish sooner. Pricing the requests no longer takes several seconds twice per estimate, and each file no longer rebuilds the translation instructions from the game's guidance: a 972-file Maps & events Batch estimate on Windows took about 87 s instead of 99 s.
- **App:** when DazedTL cannot open its workspace at start, the page says why, such as the workspace already being open in another DazedTL, instead of "A newer version of DazedTL may fix this." under a second, sometimes vaguer message.

## [2.14.2] - 2026-10-13

### Fixed

- **App:** a game with a long translation history stays responsive. Every screen update checked each saved run's files again, rereading all of them once the history passed about 20,000 files, so clicks, page switches and estimates waited seconds on Windows. The checks now reuse what they read before.

## [2.14.1] - 2026-10-13

### Changed

- **Translate:** Claude Batches keep their repeated instructions for five minutes instead of an hour. A Batch sends most of its requests at once, so many of them pay to store the instructions instead of reusing them, and the five-minute kind costs 1.25 times the input price where the hour-long kind cost twice. A 48-request Database Batch that cost $2.11 would have cost about $1.49 with the same reuse.

### Fixed

- **Translate:** a file with nothing to translate, such as an empty **Troops.json**, reads **Done** instead of **Ready to apply** while a run works and **Applied** after it, though it was never applied. **Apply**, the Project page's files applied and the Check and Release notes about applied text no longer count it.
- **Translate:** a file whose Batch results could not be saved, for example after a canceled Batch, shows **0** saved lines instead of the lines the provider returned, and the Project page's lines translated no longer counts them.
- **Translate:** a file already applied no longer reads **Ready to apply** again after **Translate** finds no new requests for it.
- **Translate:** a Guided Batch no longer stops with "The file operation could not finish." once its cost estimate is done. Since 2.13.0 it happened on every Batch for a game whose earlier translations included text stored in game variables.
- **App:** switching pages right after coming back to DazedTL from another window no longer leaves the buttons disabled until the app has reread the whole project, which took many seconds on a large game on Windows.
- **Translate:** Live translation no longer spends about two seconds starting up for every file, so a large game's run finishes many times faster: 972 map files took under 3 minutes instead of about 40. The app also stays responsive once a run has saved hundreds of files, where every screen update and **Stop** could wait about 10 seconds.
- **Translate:** a Claude Batch estimate is now a range, from every repeated instruction reused to none, instead of one figure that counted on reuse. A 48-request Database Batch estimated at $1.02 cost $2.11, which its new estimate of $1.68–$2.67 covers. The **Cost estimate** in Context, the Batch review and Assistant-led Batch estimates all show it, and an Assistant-led estimate's cost is the higher figure.
- **Translate:** run costs for Claude Opus 5.5 and Sonnet 5.5 count reused instructions at their real price, half of what DazedTL counted before, and a quarter for Fable 5.1.
- **Settings:** when the model catalog can't be loaded, **Built-in engine rates** for Claude Fable and Mythos are $10 and $50 per million tokens instead of $3 and $15, so their estimates no longer show under a third of the cost. Claude Opus 4.7 to 5.5 and Sonnet 5 and 5.5 also get their own prices instead of older models'.
- **Translate:** right after **Cancel Batch**, files read **Working** while the app saves what the Batch returned, instead of **Needs review** with "Its submission could not be confirmed" for up to half a minute, and **Run history** reads **Receiving results** meanwhile instead of a failed run with uncertain requests.

## [2.14.0] - 2026-10-13

### Added

- **Context:** when a game shows script, plugin command or comment text that DazedTL has no pattern for, the **Event text sources** investigation now writes a pattern for that game and turns it on, instead of leaving that text untranslated. **Source choices** lists the patterns written for the game.

### Removed

- **Windows:** DazedTL no longer includes four unused helper programs that Windows Security and some other antivirus programs reported as a trojan and removed. They were old reference tools that no DazedTL step runs, so nothing changes in how DazedTL works.

### Fixed

- **Context:** **Names & glossary** reads **Waiting** until its assistant saves its last result, instead of **Done** a few minutes into the copied task while the assistant was still working.
- **Context:** **Line widths** no longer waits forever when the assistant could not measure the game's windows or saved a report DazedTL can't use: it finishes with the measured widths **Skipped**, or reads **Blocked** with the reason so the assistant can fix the report.
- **Setup:** the first start tries a download again when the connection drops, instead of stopping with "fetch failed". If a download still fails, it says which one and to check the internet connection.
- **Translate:** after **Retry saving results**, files saved by an earlier attempt keep their cost and time instead of reading $0.0000 and 0.0s, so the run's total cost is right again.
- **Translate:** a Database Batch no longer fails to save with "No fetched result matches this request" for **States.json** and the files after it. **Retry saving results** now saves a Batch that already failed this way from its existing results, without sending anything again.
- **Translate:** when a canceled or partly failed Batch has no result for some of a file's lines, only that file stays unsaved, and the banner says in plain words what happened and to translate the file again with Live or a new Batch. Before, it read "No fetched result matches this request" with advice about a glossary freeze, and the files after it were not saved either.
- **Translate:** while a Batch waits for the clarification of refused requests, files whose results already arrived read **Working** instead of **Needs review**, also after a restart, and the footer says what the run waits for. Run history no longer reads **At provider** while those results are being saved.
- **Translate:** **Apply** on a large game opens its review in seconds instead of many minutes, so applying no longer fails with "This publication review expired or was already used." Applying itself is faster, **Review restore** after an interrupted Apply also opens in seconds, and each finished Apply no longer keeps a second copy of every file it wrote, about 400 MB on a large game.

## [2.13.2] - 2026-10-13

### Changed

- **Translate:** after you decline or close a cost review, clicking **Translate** again reuses that estimate while the files and settings are unchanged, instead of estimating every file again. Its window marks Estimate cost as Reused.
- **Context:** **Estimate again** in Cost estimate waits until something the estimate depends on changes, since it would give the same result. Updating DazedTL now also marks a saved estimate Outdated.

### Fixed

- **Translate:** Preview request in a Batch review pages through every request the Batch will submit. When names and labels were translated with Live first, it showed only those name requests, such as "Request 1 of 1", and none of the Batch's own.

## [2.13.1] - 2026-10-13

### Fixed

- **Project:** after DazedTL restarts, a Guided game whose last Batch was declined or stopped opens normally again. Since 2.13.0 it showed "Project unavailable" with "Model pricing is unknown. Set explicit rates in Settings before estimating." until something looked up the model's prices again.

## [2.13.0] - 2026-10-13

### Changed

- **Translate:** cost estimates for a connection without Batch, such as an OpenRouter model without a Batch endpoint or a custom endpoint, are many times faster: one for 62 files took about four minutes on Windows and now takes about eight seconds.
- **Translate:** while an estimate is prepared, its window lists the steps to the cost review (**Check files**, **Estimate cost**, then for Batch **Prepare Batch**), how long each finished step took, how many files the current step has done and about how long it has left, and the time since you clicked **Translate**. It used to show one line such as "Preparing the Batch cost review…" with no progress.
- **Context:** **Cost estimate** shows each task's progress and about how long is left while it works, and how long the last estimate took.
- **Translate:** names and labels translated with Live before a Batch now join the game glossary in **Context** > **Guidance** even when you decline the Batch, so you can see and edit them there. Completed runs already added them.
- **Translate:** cost estimates and Batch preparation are much faster, most of all on Windows. A Batch for 62 files reached its cost review in 14 seconds instead of 71, and a Claude Live estimate in 11 instead of 27: a Batch now uses the requests its estimate already built instead of reading every file twice more, and starting an estimate no longer copies and rereads the whole game several times.
- **Context:** **Cost estimate** works on Database files, Maps & events and Other event text at the same time; for a 72-file game it took 11 seconds instead of 43 on Windows.

### Fixed

- **Translate:** preparing a Batch no longer sends a paid Live request for each map place label and some plugin texts, such as `<LB:村>` notes, before you approve the Batch. They are now part of the Batch and its cost review, which also makes preparing a Batch faster.
- **Translate:** Claude Batch and Live translation on Windows no longer fail with "Could not determine home directory.", and Claude cost estimates there use Claude's own token count instead of an approximate one.
- **Translate:** for a Claude model, the **Live** cost review and **Review names and labels** now count input tokens the way Anthropic bills them, as the Batch review has since 2.11.2; they read about 10% and a third low. When Anthropic's token count can't be reached, the review says the input is approximate.
- **Translate:** a Batch that failed before anything was sent, for example because its connection could not be set up, now reads "Failed · unsent" in Run history instead of "Check submission", and translating those files again no longer warns that it may charge twice.
- **Translate:** when a newer run exists, the warning about a Batch that could not be confirmed as sent now names that Batch by its start time instead of calling it the last Batch.
- **Translate:** starting a cost estimate no longer shows "The operation could not finish." or leaves the cost review stuck on "Preparing the Batch cost review…". If that error appears for another reason while work runs, it now clears by itself once DazedTL can read the project again, instead of progress freezing until you reload.
- **Translate:** names and labels translated with Live before a Batch are no longer lost when one of them has its own parentheses, such as "Farmer's Soul (Husband)". The Batch review said "Name translation result unavailable", and the next run asked to pay for every name again. Names from those earlier runs are now reused, and a name that still can't be saved is listed on its own instead of discarding the rest.
- **Translate:** **Run history** > **Inspect** now shows the names and labels translated with Live before a Batch as their own **Names and labels · Live** group, also once the Batch is prepared or sent. They were listed as "Requests without a batch receipt" under one map, or not at all, and counted as that map's translated lines, so a declined Batch could show lines translated on the **Project** page.
- **Translate:** an OpenRouter Batch whose new names and labels need translating first no longer stops with "Speaker translation canceled"; OpenRouter refused those Live requests with "No allowed providers are available for the selected model".
- **Context:** glossary entries whose translation has its own parentheses, such as `ヴィクター（釣り竿） (Victor (Fishing Rod))`, now reach translation; they were ignored before.

## [2.12.0] - 2026-10-12

### Added

- **Context:** the new **Cost estimate** task shows what translating the whole game with your API key costs before you translate anything: Database files, Maps & events and Other event text over all their files, each with its cost, in Batch or Live. It is free, and it reads **Outdated** once the guidance, sources, game files or model change.

### Changed

- **Context:** the Other event text investigation and its **Source choices** moved from Translate to a new Context task, **Event text sources**, so the sources are chosen before the cost estimate; **Other event text** in Translate now only translates them.
- **Context:** **Event text sources** findings now keep spaces in translated plugin labels and popups where the plugin allows it, instead of underscores, and leave placeholders untranslated instead of turning off their whole source; investigate again in games already in progress.

### Fixed

- **Translate:** **Other event text** no longer says "Saved translations applied." after Maps & events is applied, before its own translations are.

## [2.11.2] - 2026-10-12

### Fixed

- **Translate:** Claude estimates now count input tokens the way Anthropic bills them. They used to count only the shared instructions that way and the rest with a generic count, so a large Batch estimate read about 10% low: 19.2 instead of 21.5 million input tokens on a 970-map game.
- **Assistant-led:** API estimates on Claude now count input tokens the way Anthropic bills them; a large estimate used to read about a third low.

## [2.11.1] - 2026-10-12

### Changed

- **Plugin files:** reviewing and applying translated plugins is faster, most of all on Windows: the app checks each unchanged script once instead of again for every file in the review.

### Fixed

- **Plugin files:** a script check that never finishes now stops at its time limit with a message saying so, instead of an internal error.

## [2.11.0] - 2026-10-12

### Changed

- **Translate:** short RPG Maker MV/MZ event pages in maps, common events and troops now share requests instead of costing one each, and a longer page's choice menus go with its dialogue; on a 970-map game a Maps & events estimate fell from 4,089 to 2,173 requests and from 23.5 to 14.0 million input tokens. Runs started before the update keep their old requests.
- **Assistant-led:** API runs cost less: lines go to the model by number instead of by their long names, estimates count tokens the way Guided does, and a scene longer than 10 lines gets its own request. On a large test game input fell from 22.5 to 17.6 million tokens and output from 9.1 to 7.2 million. Runs started before the update keep their old requests.
- **Assistant-led:** when your assistant saves an RPG Maker message one line at a time, preparing requests stops and asks it to save whole messages, which otherwise multiplies requests and cuts sentences apart.
- **Translate:** the run inspector shows a run's requests 100 at a time, with Previous and Next beside the picker.

### Fixed

- **Assistant-led:** approving an API estimate for a very large game no longer stops with "Choose a regular JSON file within the supported size limit."
- **Assistant-led:** the app no longer freezes, or reports that it stopped responding, while your assistant prepares requests for a big game; Estimate and Compile show their progress beside the button.
- **Assistant-led:** large Batch runs save their results much faster (about 30 seconds down to 5 for 2,600 requests) and use far less memory and disk while a retry of refused requests waits.
- **Assistant-led:** Cancel while a retry of refused requests waits now cancels that retry and keeps everything already finished; a canceled run no longer reads "The provider batch failed." or leaves its later parts waiting, and parts never sent read "Not sent".
- **Assistant-led:** animation and tileset names, which players never see, no longer have to be extracted and paid for before a complete estimate.
- **Translate:** preparing a Batch on Windows no longer fails with "PermissionError: manual run failed" or "[WinError 32]".
- **Translate:** the app answers faster while a large Batch run is open; on a 1,500-map game each refresh at the Batch review went from about 1 second to half that, and the review opens in about 2 seconds instead of 5.
- **Translate:** "Saved process evidence is unavailable" no longer flashes while a Batch collects its results, and a submission that may not have reached the provider reads as unconfirmed instead of "This request has not been sent."
- **Project:** a running Assistant-led step shows once instead of twice.

## [2.10.0] - 2026-10-12

### Added

- **Settings:** a new Notifications tab plays a sound, shows a desktop notification, or both, when a translation or other long step finishes, when work waits for your approval, and when your assistant hands back a task or needs you. Choose your own sound file or keep the built-in chime.

### Fixed

- **Translate:** a Batch estimate for a very large game, such as one with about 1,000 maps, no longer stops with "Choose a regular JSON file within the supported size limit."
- **Translate:** the app responds faster while a very large Batch run is shown, for example during its cost review.

## [2.9.1] - 2026-10-12

### Added

- **Assistant-led:** Wolf Pro games that keep their own archive key beside their archives now open and unpack, including archives renamed to .data, .pak and similar.
- **Assistant-led:** the bundled Wolf tools read and rewrite data files protected by Wolf 2.x and Wolf Pro 3.1 to 3.5.

### Fixed

- **Guided:** large games no longer make the app slow to answer; on a 5,000-file game each refresh took 2 to 3 seconds on Windows and every click waited behind it, and now takes under a tenth of a second.
- **Set up:** on large games the Context page opens as soon as Save version finishes, instead of about 20 seconds later on Windows; setting up a 2.5 GB test game on Windows went from about 1.5 minutes to under 1.
- **Project:** Wolf games whose archives sit in a Data folder no longer stay at "Investigation pending".
- **Assistant-led:** unpacking a Wolf archive reports how many files it held, instead of "? files" and a total of 0.

## [2.9.0] - 2026-10-11

### Changed

- **Settings:** Updates shows the notes of every earlier version too, a few versions at a time, instead of only the newest.

## [2.8.2] - 2026-10-11

### Fixed

- **Playtest:** MV games no longer fail at Menu screens and Battle, or at every stop after a crash.
- **Text QA:** capturing the game's screens goes on past a screen that stops or freezes the game, instead of waiting out its time limit and missing the screens after it, and it now works on Linux without a display.

## [2.8.1] - 2026-10-11

### Fixed

- **Set up:** Back up the original and Save version no longer take several minutes each on large games, most of all on Windows; setting up a 2.5 GB test game on Windows went from about 9 minutes to 1.5.

## [2.8.0] - 2026-10-11

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

## [2.7.0] - 2026-10-11

### Added

- **Text QA:** your assistant now works through screening, deep review, a consistency sweep and an editorial pass on its own, and corrections apply once they pass; you only answer the questions reviewers couldn't settle.
- **Text QA:** the page shows each stage, what QA is doing now and the time left, and lists corrections by category with Undo and Apply again on each one.
- **Text QA:** another reviewer screens at least a quarter of each reviewer's lines again, and checks every line of a reviewer that misses problems.
- **Text QA:** one correction can fix several lines of a scene together, such as narration that switches tense partway through.
- **Text QA:** checks database entries whose different names share one English name, glossary terms a database text leaves out, battle messages without the battler's name, and speech shown with another character's face or nameplate.
- **Text QA:** lists Japanese that was never translated, such as custom data files and plugin settings, and whether players can see it.
- **History:** a Text QA apply or undo can be restored like other text batches.
- **Assistant-led:** RPG Maker MV/MZ and VX Ace games get DazedTL's text QA in the run, with a Text QA tab and its progress on Progress.
- **Versions:** the Game updates tab is now Versions, with steps for choosing, comparing, applying and translating an update, and a list of the game's earlier versions.
- **Versions:** apply a developer's patch as well as a complete game; DazedTL tells which one the folder holds and lines up extra folders and MV's www folder.
- **Versions:** see an update's text changes line by line before applying it: what is new to translate and which translations go back to Japanese.
- **Versions:** after a Guided update, the last step lists the tasks whose files changed and opens them with those files selected.
- **Names & glossary:** the assistant checks likely speaker slips, a face or nameplate that belongs to another character, and fixes them; Speaker names shows what it fixed or kept and why.
- **Names & glossary:** the glossary records how characters address role titles, such as 隊長さん (Captain-san), so translations keep that address.

### Changed

- **Translate:** live translation shows the model the English it already wrote for the lines just before, so a scene split across requests keeps its tense and forms of address.
- **Translate:** the translation prompt is stricter about addressing the listener as "you", honorifics on titles, moans and other voiced sounds, and keeping one tense in a scene's narration.
- **Translate:** MV/MZ translation fixes the spacing after ♥ and stray letters from a small っ as it translates, and Text QA applies those fixes without review.
- **Translate:** new MV/MZ runs tell the model which characters use each skill in battle messages, so pronouns fit, and treat a party that only ever holds one character as that character.
- **GameUpdate:** the repository and its status moved to the Guided Release task and Assistant-led Options.

### Fixed

- **Versions:** applying an update no longer drops translations next to lines the new release added; text the release left unchanged keeps its translation.
- **Versions:** a patch folder no longer replaces the whole game, which removed every file the patch didn't hold.
- **Versions:** a second update no longer shows "Last run: complete" from the update before it.
- **Translate:** maps a game update adds show up without restarting DazedTL.
- **Translate:** MV and Ace battle messages keep the space after the battler's name, instead of showing "Haroldfell!".
- **Translate:** in new runs, a line that starts with a name in 【】 or before 「 no longer gets that name written twice.
- **Text QA:** "First Stratum" for 第1層 and "Increases TP by 24" for TP24 no longer count as number mistakes.
- **Text QA:** a QA task DazedTL can't read shows Blocked with the reason instead of Not started, and Run QA again starts a fresh one.
- **Text QA:** after you undo every correction it reads Done instead of "Applied · 0 corrections applied", and "QA task copied" no longer comes back once QA has finished.
- **Text QA:** saving the version after applying QA no longer fails with "Supply the matching untranslated original" on games set up with their translation already in Git.
- **Windows:** QA files your assistant saved from an administrator PowerShell no longer stop DazedTL with "Permission denied".
- **Settings:** links about API connections open the connection settings instead of the last section you viewed.

## [2.6.1] - 2026-10-10

### Added

- **Settings > Updates:** shows what's new in an update before you restart, and what changed since your previous version after it.
- `CHANGELOG.md` lists what changed in every version since 2.0.0.

### Fixed

- **Text QA:** a prepared QA task no longer turns Outdated when DazedTL fills in the game's GameUpdate repository; saved Translate estimates and line width checks stay current too.

## [2.6.0] - 2026-10-10

### Added

- **Settings > GameUpdate:** choose the forge, host, owner and branch players update from, and DazedTL writes and commits each game's patch config for you.
- **Game updates:** shows the game's repository and whether its patch config is current.

### Fixed

- A review with one added file says "1 file is an addition" instead of "1 files are additions".

## [2.5.4] - 2026-10-10

### Fixed

- **Set up:** saving the game's first version no longer stops with "Bundled GameUpdate .gitignore is unavailable".

## [2.5.3] - 2026-10-10

### Fixed

- **GameUpdate:** Wolf games no longer get a patch config that points to another game's repository.
- **GameUpdate:** the README for players now only explains how to patch, update and fix problems.
- **GameUpdate:** without UberWolf, players are told how to unpack Data.wolf themselves.

## [2.5.2] - 2026-10-10

### Changed

- **Text QA:** the "Running jokes and terms" row is gone, since **Names & glossary** already finds them.

## [2.5.1] - 2026-10-09

### Added

- **Assistant-led:** YU-RIS games get their window title translated, and line breaks in translations show in the game.

### Changed

- **Copy diagnostics** now includes errors your assistant ran into.

### Fixed

- **Assistant-led:** the assistant can correct lines it already translated; this used to fail with "The project operation could not finish."
- **Assistant-led:** game text at the top of a decoded game dump is no longer set aside as text players never see.

## [2.5.0] - 2026-10-09

### Added

- **Assistant-led:** YU-RIS games can be translated.
- **Assistant-led:** the count of a Unity game's text now includes the text inside its asset files.

### Changed

- **Assistant-led:** your assistant can set aside text players never see in any kind of game file, and **Progress** lists its rules.
- **Assistant-led:** the assistant waits about a second for quick steps instead of 15.

### Fixed

- **Set up:** stopping it no longer leaves gigabytes of temporary files behind, and **Finish setup** works again afterwards.
- **Set up:** no longer fails on Windows when DazedTL is reading the game's files at the same moment.
- **Set up:** no longer fails with "Symbolic links are not supported in game trees" when your assistant made a Python environment in the project.
- **Assistant-led:** the assistant can no longer package a game before all of its text is extracted.
- **Assistant-led:** Git setup accepts files the patch will add, such as a Unity mod loader.
- **Set up:** when it is interrupted, it says to run it again instead of showing a message meant for translation runs.

## [2.4.4] - 2026-10-09

### Fixed

- **Translation:** every passage a model refuses gets the clarification retry when it is allowed, not just some of them.

## [2.4.3] - 2026-10-09

### Fixed

- **Guided:** the workspace no longer stalls while looking up model prices.
- **Assistant-led:** the project no longer fails to load after a restart while an estimate waits for approval.
- **Translation:** a slow price lookup gives up after five seconds and says to try again or enter custom rates in **Settings**.

## [2.4.2] - 2026-10-09

### Changed

- **Assistant-led:** requests are sized for the translation mode, and a request holding several scenes names each one, so the model keeps their speakers apart.

## [2.4.1] - 2026-10-09

### Fixed

- **Assistant-led:** the count of a game's text leaves out mod loaders, readmes and credits, and reads more KAG3 scripts.
- **Assistant-led:** your assistant's rules no longer set aside text from decoded game dumps.

## [2.4.0] - 2026-10-09

### Added

- **Assistant-led:** DazedTL counts the game's Japanese text itself, and the assistant can only finish extracting once every line is covered.
- **Progress:** shows how much of the game's text is covered, and what was set aside as text players never see.

### Changed

- **Assistant-led:** the assistant translates everything the count finds; it can only decline lines, which another model can then translate.

### Fixed

- **Closing DazedTL:** a forced stop now ends every process the app started, including stuck Git commands.

## [2.3.1] - 2026-10-09

### Added

- **Copy diagnostics:** now records what the app was waiting on when something hangs for more than 30 seconds.

### Changed

- **Guided:** the workspace starts far fewer background Git commands while idle, which makes it faster on Windows.

## [2.3.0] - 2026-10-09

### Added

- **Assistant-led:** the assistant hands the game's lines to DazedTL to group into requests, instead of rewriting the game text itself.
- **Assistant-led:** in **Assistant only**, lines the assistant won't translate appear under **Declined lines** on **Progress**, where another model can finish them.

### Fixed

- **Assistant-led:** Git setup no longer fails with "Unexpected UTF-8 BOM" when the assistant uses Windows PowerShell.

## [2.2.3] - 2026-10-09

### Added

- **Assistant-led:** images have their own phase on **Progress**, so translation finishes with the text.

### Changed

- **Progress:** shows one current phase, marks finished phases with a green check, and half fills a phase left unfinished.

### Fixed

- **Assistant-led:** an estimate priced with settings you changed since can no longer be approved; **Progress** asks for a new one.

## [2.2.2] - 2026-10-09

### Added

- **Assistant-led:** approve the assistant's API estimates on **Progress**, without opening Run history.
- **Assistant-led:** the assistant translates images through the Image Manager.

### Fixed

- **Assistant-led:** packaged projects no longer show "Workspace unavailable".
- **Assistant-led:** packaging no longer refuses after a progress report with "uncommitted changes".
- **Assistant-led:** **Progress** stops asking you to copy the starting prompt once the assistant has reported.
- **Images:** deleting the game's work folder no longer makes the workspace unavailable.

## [2.2.1] - 2026-10-09

### Fixed

- **Assistant-led:** **Progress** stops asking you to approve a run that has already started.
- **Assistant-led:** "last active" shows when the assistant last worked, not when the API run last checked in.
- **Assistant-led:** backup warnings for deleted backups no longer come back on every visit.

## [2.2.0] - 2026-10-08

### Added

- **Assistant-led:** **Start over** brings back the original game and keeps the earlier attempt in an archive folder.

### Changed

- **Wolf games:** the bundled WolfDawn tools are updated, with better text reflow.

### Fixed

- **Assistant-led:** **Progress** shows the run has started before the assistant's first report.
- **Assistant-led:** turning an option off and on again no longer stops **Copy prompt** with "Save or discard project drafts".
- Page headers keep the same height whether or not they have buttons.

## [2.1.0] - 2026-10-08

### Added

- **Names & glossary:** **Thorough investigation** looks for names and running jokes in three independent passes.

### Changed

- **Assistant-led:** new games start on API Batch, the starting prompt runs the whole method on its own, and **Progress** leads with the assistant's status.

### Fixed

- The workspace opens even when one project can't be read, and **Settings > Updates** stays reachable when it can't open.
- **Guided:** a stopped run says it stopped instead of "Run finished".
- **Guided:** each task's **Apply** confirms only its own files.
- **Guided:** an **Apply** right after a run no longer fails with "The saved output, destination or settings changed".
- **Guided:** a rerun keeps the line counts of files it carried over.
- **Images:** the assistant's recommendations are ticked as soon as its report arrives.
- **Game updates:** the changed-file list fills the page.
- **Windows:** START works from a PowerShell 7 terminal, and shortcuts keep non-English folder names.
- A second copy of DazedTL no longer takes over the shortcuts of a newer one.

## [2.0.9] - 2026-10-08

### Changed

- **Settings:** a connection is checked as soon as you save it.
- The workspace stays responsive on Windows, where it used to start Git many times a second.
- Updating no longer reinstalls packages when only DazedTL's version changed.

### Fixed

- **Windows:** Live runs no longer freeze at "Preparing an isolated copy".
- **Windows:** assistant tasks give PowerShell commands that work, including with Japanese text.
- **Windows:** building the release ZIP no longer fails after two minutes.
- **Windows:** the engine writes text files with the same line endings as on Linux.
- **Windows:** START no longer warns about its publisher on every start.
- **Windows:** Restart to update no longer leaves a console window open.
- **Windows:** copying the Images investigation task no longer fails with a path error.
- **Windows:** assistant tasks that use Git point to DazedTL's own Git.
- **Settings:** a refused local connection no longer reads as a certificate problem.
- **Settings > Updates:** no longer reports a crash after every successful update.
- **Updates:** the interface is rebuilt whenever its files change, so a new version never shows the old interface.

## [2.0.8] - 2026-10-08

### Fixed

- **Windows:** DazedTL brings its own Git, so games can be set up without installing Git.
- **Windows:** the START console is titled DazedTL and no longer shows a build timing report.

## [2.0.7] - 2026-10-08

### Fixed

- **Windows:** the first start no longer stops at "Installing Electron" on a fresh Windows.

## [2.0.6] - 2026-10-08

### Fixed

- **Windows:** project operations no longer end as "interrupted" as soon as they start.
- **Windows:** saving a run no longer fails while another part of the app reads the same file.

## [2.0.5] - 2026-10-08

### Fixed

- **Windows:** projects open instead of showing "Project unavailable".
- **Windows:** games in folders with Japanese names open.

## [2.0.4] - 2026-10-08

### Fixed

- **Windows:** the app builds and opens instead of stopping during START.

## [2.0.3] - 2026-10-08

### Fixed

- **Project:** **Change method** only appears when another method applies.
- **Setup:** the first start no longer tells you to update npm.

## [2.0.2] - 2026-10-08

### Changed

- The README and user guide are rewritten in plain language.

## [2.0.1] - 2026-10-08

### Fixed

- **Updates:** downloads from GitGud work.
- **Updates:** an update runs the new version's setup on the first start after it.

## [2.0.0] - 2026-10-08

### Added

- The first release of DazedTL as a desktop app, installed from a ZIP with a START launcher and updated from inside the app.
- **Guided steps** for RPG Maker MV, MZ and VX Ace games, and **Assistant-led** for any game.

[2.44.0]: https://github.com/dazedanon/DazedTL/compare/v2.43.0...v2.44.0
[2.43.0]: https://github.com/dazedanon/DazedTL/compare/v2.42.0...v2.43.0
[2.42.0]: https://github.com/dazedanon/DazedTL/compare/v2.41.0...v2.42.0
[2.41.0]: https://github.com/dazedanon/DazedTL/compare/v2.40.2...v2.41.0
[2.40.2]: https://github.com/dazedanon/DazedTL/compare/v2.40.1...v2.40.2
[2.40.1]: https://github.com/dazedanon/DazedTL/compare/v2.40.0...v2.40.1
[2.40.0]: https://github.com/dazedanon/DazedTL/compare/v2.39.0...v2.40.0
[2.39.0]: https://github.com/dazedanon/DazedTL/compare/v2.38.1...v2.39.0
[2.38.1]: https://github.com/dazedanon/DazedTL/compare/v2.38.0...v2.38.1
[2.38.0]: https://github.com/dazedanon/DazedTL/compare/v2.37.0...v2.38.0
[2.37.0]: https://github.com/dazedanon/DazedTL/compare/v2.36.4...v2.37.0
[2.36.4]: https://github.com/dazedanon/DazedTL/compare/v2.36.3...v2.36.4
[2.36.3]: https://github.com/dazedanon/DazedTL/compare/v2.36.2...v2.36.3
[2.36.2]: https://github.com/dazedanon/DazedTL/compare/v2.36.1...v2.36.2
[2.36.1]: https://github.com/dazedanon/DazedTL/compare/v2.36.0...v2.36.1
[2.36.0]: https://github.com/dazedanon/DazedTL/compare/v2.35.0...v2.36.0
[2.35.0]: https://github.com/dazedanon/DazedTL/compare/v2.34.5...v2.35.0
[2.34.5]: https://github.com/dazedanon/DazedTL/compare/v2.34.4...v2.34.5
[2.34.4]: https://github.com/dazedanon/DazedTL/compare/v2.34.3...v2.34.4
[2.34.3]: https://github.com/dazedanon/DazedTL/compare/v2.34.2...v2.34.3
[2.34.2]: https://github.com/dazedanon/DazedTL/compare/v2.34.1...v2.34.2
[2.34.1]: https://github.com/dazedanon/DazedTL/compare/v2.34.0...v2.34.1
[2.34.0]: https://github.com/dazedanon/DazedTL/compare/v2.33.2...v2.34.0
[2.33.2]: https://github.com/dazedanon/DazedTL/compare/v2.33.1...v2.33.2
[2.33.1]: https://github.com/dazedanon/DazedTL/compare/v2.33.0...v2.33.1
[2.33.0]: https://github.com/dazedanon/DazedTL/compare/v2.32.1...v2.33.0
[2.32.1]: https://github.com/dazedanon/DazedTL/compare/v2.32.0...v2.32.1
[2.32.0]: https://github.com/dazedanon/DazedTL/compare/v2.31.0...v2.32.0
[2.31.0]: https://github.com/dazedanon/DazedTL/compare/v2.30.0...v2.31.0
[2.30.0]: https://github.com/dazedanon/DazedTL/compare/v2.29.0...v2.30.0
[2.29.0]: https://github.com/dazedanon/DazedTL/compare/v2.28.0...v2.29.0
[2.28.0]: https://github.com/dazedanon/DazedTL/compare/v2.27.2...v2.28.0
[2.27.2]: https://github.com/dazedanon/DazedTL/compare/v2.27.1...v2.27.2
[2.27.1]: https://github.com/dazedanon/DazedTL/compare/v2.27.0...v2.27.1
[2.27.0]: https://github.com/dazedanon/DazedTL/compare/v2.26.0...v2.27.0
[2.26.0]: https://github.com/dazedanon/DazedTL/compare/v2.25.0...v2.26.0
[2.25.0]: https://github.com/dazedanon/DazedTL/compare/v2.24.0...v2.25.0
[2.24.0]: https://github.com/dazedanon/DazedTL/compare/v2.23.1...v2.24.0
[2.23.1]: https://github.com/dazedanon/DazedTL/compare/v2.23.0...v2.23.1
[2.23.0]: https://github.com/dazedanon/DazedTL/compare/v2.22.0...v2.23.0
[2.22.0]: https://github.com/dazedanon/DazedTL/compare/v2.21.0...v2.22.0
[2.21.0]: https://github.com/dazedanon/DazedTL/compare/v2.20.1...v2.21.0
[2.20.1]: https://github.com/dazedanon/DazedTL/compare/v2.20.0...v2.20.1
[2.20.0]: https://github.com/dazedanon/DazedTL/compare/v2.19.0...v2.20.0
[2.19.0]: https://github.com/dazedanon/DazedTL/compare/v2.18.0...v2.19.0
[2.18.0]: https://github.com/dazedanon/DazedTL/compare/v2.17.0...v2.18.0
[2.17.0]: https://github.com/dazedanon/DazedTL/compare/v2.16.0...v2.17.0
[2.16.0]: https://github.com/dazedanon/DazedTL/compare/v2.15.1...v2.16.0
[2.15.1]: https://github.com/dazedanon/DazedTL/compare/v2.15.0...v2.15.1
[2.15.0]: https://github.com/dazedanon/DazedTL/compare/v2.14.2...v2.15.0
[2.14.2]: https://github.com/dazedanon/DazedTL/compare/v2.14.1...v2.14.2
[2.14.1]: https://github.com/dazedanon/DazedTL/compare/v2.14.0...v2.14.1
[2.14.0]: https://github.com/dazedanon/DazedTL/compare/v2.13.2...v2.14.0
[2.13.2]: https://github.com/dazedanon/DazedTL/compare/v2.13.1...v2.13.2
[2.13.1]: https://github.com/dazedanon/DazedTL/compare/v2.13.0...v2.13.1
[2.13.0]: https://github.com/dazedanon/DazedTL/compare/v2.12.0...v2.13.0
[2.12.0]: https://github.com/dazedanon/DazedTL/compare/v2.11.2...v2.12.0
[2.11.2]: https://github.com/dazedanon/DazedTL/compare/v2.11.1...v2.11.2
[2.11.1]: https://github.com/dazedanon/DazedTL/compare/v2.11.0...v2.11.1
[2.11.0]: https://github.com/dazedanon/DazedTL/compare/v2.10.0...v2.11.0
[2.10.0]: https://github.com/dazedanon/DazedTL/compare/v2.9.1...v2.10.0
[2.9.1]: https://github.com/dazedanon/DazedTL/compare/v2.9.0...v2.9.1
[2.9.0]: https://github.com/dazedanon/DazedTL/compare/v2.8.2...v2.9.0
[2.8.2]: https://github.com/dazedanon/DazedTL/compare/v2.8.1...v2.8.2
[2.8.1]: https://github.com/dazedanon/DazedTL/compare/v2.8.0...v2.8.1
[2.8.0]: https://github.com/dazedanon/DazedTL/compare/v2.7.0...v2.8.0
[2.7.0]: https://github.com/dazedanon/DazedTL/compare/v2.6.1...v2.7.0
[2.6.1]: https://github.com/dazedanon/DazedTL/compare/v2.6.0...v2.6.1
[2.6.0]: https://github.com/dazedanon/DazedTL/compare/v2.5.4...v2.6.0
[2.5.4]: https://github.com/dazedanon/DazedTL/compare/v2.5.3...v2.5.4
[2.5.3]: https://github.com/dazedanon/DazedTL/compare/v2.5.2...v2.5.3
[2.5.2]: https://github.com/dazedanon/DazedTL/compare/v2.5.1...v2.5.2
[2.5.1]: https://github.com/dazedanon/DazedTL/compare/v2.5.0...v2.5.1
[2.5.0]: https://github.com/dazedanon/DazedTL/compare/v2.4.4...v2.5.0
[2.4.4]: https://github.com/dazedanon/DazedTL/compare/v2.4.3...v2.4.4
[2.4.3]: https://github.com/dazedanon/DazedTL/compare/v2.4.2...v2.4.3
[2.4.2]: https://github.com/dazedanon/DazedTL/compare/v2.4.1...v2.4.2
[2.4.1]: https://github.com/dazedanon/DazedTL/compare/v2.4.0...v2.4.1
[2.4.0]: https://github.com/dazedanon/DazedTL/compare/v2.3.1...v2.4.0
[2.3.1]: https://github.com/dazedanon/DazedTL/compare/v2.3.0...v2.3.1
[2.3.0]: https://github.com/dazedanon/DazedTL/compare/v2.2.3...v2.3.0
[2.2.3]: https://github.com/dazedanon/DazedTL/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/dazedanon/DazedTL/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/dazedanon/DazedTL/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/dazedanon/DazedTL/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/dazedanon/DazedTL/compare/v2.0.9...v2.1.0
[2.0.9]: https://github.com/dazedanon/DazedTL/compare/v2.0.8...v2.0.9
[2.0.8]: https://github.com/dazedanon/DazedTL/compare/v2.0.7...v2.0.8
[2.0.7]: https://github.com/dazedanon/DazedTL/compare/v2.0.6...v2.0.7
[2.0.6]: https://github.com/dazedanon/DazedTL/compare/v2.0.5...v2.0.6
[2.0.5]: https://github.com/dazedanon/DazedTL/compare/v2.0.4...v2.0.5
[2.0.4]: https://github.com/dazedanon/DazedTL/compare/v2.0.3...v2.0.4
[2.0.3]: https://github.com/dazedanon/DazedTL/compare/v2.0.2...v2.0.3
[2.0.2]: https://github.com/dazedanon/DazedTL/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/dazedanon/DazedTL/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/dazedanon/DazedTL/releases/tag/v2.0.0
