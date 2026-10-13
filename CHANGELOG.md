# Changelog

Every DazedTL release, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
[release.mjs](scripts/release.mjs) writes each entry from [release/notes.md](release/notes.md).

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
