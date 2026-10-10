# Changelog

Every DazedTL release, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
[release.mjs](scripts/release.mjs) writes each entry from [release/notes.md](release/notes.md).

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
