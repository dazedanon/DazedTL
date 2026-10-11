<!-- The next release's notes; see docs/development.md#release-notes. -->

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
