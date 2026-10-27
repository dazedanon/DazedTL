# Development

This guide covers working on DazedTL: setup, checks and releases.
For installing and using the app, see the [README](../README.md) and the [user guide](user-guide.md).

## Setup

The repository includes the engine code, worker helpers, tokenizers, native tools and translation toolkit.
See [resource ownership](architecture.md#ownership) for the engine and shared prompt locations, saved-run compatibility and override behavior.

```sh
node scripts/setup.mjs
node scripts/build.mjs
node scripts/start.mjs
```

Setup installs the pinned Python from [.python-version](../.python-version), the locked packages including the formatting, lint and type-check tools, and Electron into `.runtime`, `.venv` and `app/node_modules`.
It runs npm from the pinned Node in [.node-version](../.node-version), downloading it on Linux and macOS; on Windows it uses the Node that runs it until `START.bat` has installed the pinned one.
On Windows it also installs Git for Windows' portable MinGit from [.mingit-version](../.mingit-version); other systems need their own `git`.
The scripts run on any Node release within the pinned major version.
After changing a version file, run `node scripts/runtimes.mjs` to pin the new downloads in [runtimes.lock](../scripts/runtimes.lock).

`node scripts/start.mjs` keeps the app attached to the terminal; `START` launchers detach it.
Both repeat a setup step only when its inputs change and rebuild a stale interface.
Use `node scripts/start.mjs --offline` to inspect the UI with provider execution disabled.

The app keeps projects, credentials and runs in the `DazedTL2` profile in the system's application data folder (`%APPDATA%` on Windows, `~/.config` on Linux).
An existing pre-release `DazedTLNext` profile keeps being used.

| Optional environment variable | Purpose |
| --- | --- |
| `DAZEDTL_PYTHON` | Python executable with backend dependencies; setup creates `.venv` from it instead of the pinned Python |
| `DAZEDTL_PROFILE` | Electron profile location |
| `DAZEDTL_WORKSPACE` | Project and run storage location |

## Checks

Run the full behavior suite with `node scripts/test.mjs` (or `npm test` from `app`).
It uses the local Python environment and Node's built-in test runner, with one enforced wall-clock budget including startup, fixtures, and teardown.
The budget is 10 seconds; `DAZEDTL_TEST_BUDGET` sets another in seconds, which [CI](#live-test) does for its slower runners.
The Python and Node suites run at the same time, and Python keeps its compiled modules in `.runtime/test-bytecode` between runs, so a first run after a change compiles again.
[tests/run.py](../tests/run.py) runs the Python tests in up to eight worker interpreters at once: each test module is one unit, a slow one split into parts, and the slowest start first, by the times the last passing run saved in `.runtime/test-times.json`.
Tests that start a process of their own, such as the [probes](../tests/probe.py), start it while their module is imported, so their module stays whole and the other workers overlap it.
A module's tests run after whatever other modules its worker ran before, so a test that puts stand-ins in `sys.modules` uses `replaced_modules` from [tests/engine.py](../tests/engine.py), which leaves every module as it was.
The runner reports the five slowest Python tests to make runtime regressions visible.
If a Python process is still running a second before the budget ends, it prints every thread's stack, which names the test and line it waits on, and exits.
Tests use temporary workspaces and controlled API responses; no provider, game folder or credentials are needed.

`node scripts/test.mjs` is the suite entry: it orders and parallelizes the modules and holds the budget, while a plain `python -m unittest discover` runs them serially, about 12 seconds, and ignores it.
For focused iteration, use `.venv/bin/python -I -B -m unittest discover -s tests -t . -p test_projects.py` or `node --test --test-isolation=none tests/application.test.ts` from the root.
Run `node scripts/build.mjs` separately for static checks and the renderer build.
It checks formatting, that stylesheets use the [design tokens](architecture.md#visual-design), that the [generated API contracts](architecture.md#api-changes) are current and that tracked paths fit the [Windows path budget](architecture.md#distribution-and-updates).
It lints with type-aware [Oxlint](../.oxlintrc.json) (including the React hooks rules) and [Ruff](../pyproject.toml), and type-checks the renderer, the Electron main process and DazedTL-owned Python with [Pyright](../pyproject.toml).
Of the bundled engine, only Text QA ([util/qa](../backend/dazedtl/engine/util/qa/__init__.py)) gets the same Ruff rules, through its own [settings](../backend/dazedtl/engine/util/qa/ruff.toml), and Pyright.
Ruff also rejects file and process calls that go around the [platform layer](../backend/dazedtl/system.py), in the bundled engine too through its own [settings](../backend/dazedtl/engine/ruff.toml), and text files opened without an encoding.
[platform_calls](../scripts/platform_calls.py) adds the calls Ruff cannot see, in the files Ruff checks: `Path.replace`, `Path.rename`, `Path.unlink` and `Path.rmdir`, raw reads of run records such as `job.json` and `plan.json`, and `project_path` of files a run replaces.
Launching builds a missing renderer without these checks.
Format with `node scripts/format.mjs`; it applies Prettier and Ruff defaults and leaves the bundled engine, Markdown and JSON unchanged.

## Live test

`node scripts/e2e.mjs` installs the checkout the way a user's downloaded ZIP is installed and drives the running app through a translation.
It copies the files Git would commit, including uncommitted changes, into a doubled `DazedTL-main (1)` folder and runs START with a PATH that has no Node or Python, and on Windows no Git.
The profile and a copy of the [fixture game](../tests/fixtures/mz-game) sit in folders with spaces and Japanese names; the copy takes the `event-text` and `choice-help` [game variants](#test-scenarios), so Comment text comes on for the menu's choice help.
Through the window it opens the game, runs Set up, translates and applies the database and the maps with Live translation against a local stand-in provider, stands in for the assistant's Event text sources investigation and translates and applies Other event text, opens Check and runs the Text QA assistant's playtest through the project helper, which checks the files and reports that the fixture game has no engine to play, and builds a patch ZIP, which must hold the translated database and none of DazedTL's own files.
It then builds a clean game ZIP and checks that its one top folder takes the archive's name, that it holds the translated game and that notes and a spellcheck folder added beside the game stay out.
Finally it closes the window and expects every app process to exit with no failures in the app's diagnostics, and starts again to check that setup does not repeat.
Logs, screenshots and the app's diagnostics land in `logs` inside the work folder; `--work <empty folder>` chooses it.

`--upgrade-from <tag>` runs the upgrade test instead, and `--upgrade-from previous` takes the latest earlier stable release: the release at that tag runs its own live test on the same game in `previous` inside the work folder, then this checkout is left for that install's launcher as a signed update, under a key made for the test that the install trusts.
START applies it, and the test checks that every Database files and Maps & events file reads its lines from the file, the choice help included, translates what is left, and expects the project to read every line translated and applied.
The previous release's own logs land in `previous/logs`.
On Linux the app needs a display: CI runs it under `xvfb-run`, and on a desktop a private virtual compositor keeps its window off yours, such as `dbus-run-session -- kwin_wayland --virtual --xwayland --no-lockscreen --socket e2e` with `WAYLAND_DISPLAY=e2e`.
Without `--no-lockscreen` it starts locked while your own session is locked, and the live test fails at its first screenshot.
It adds two X displays; set `DISPLAY` to the lower-numbered one, such as `:2` beside `:3`, since KWin keeps the other for its own startup.
Its stand-in provider, window driver and journey steps are the [test scenarios'](#test-scenarios) own, in [scripts/testkit](../scripts/testkit).

[CI](../.github/workflows/ci.yml) runs the build checks, the behavior tests, the [previous-release QA check](#previous-release-qa-check), the live test, the upgrade test from the latest earlier stable release and every [test scenario](#test-scenarios) on Windows and Linux for every push to `dev` and `main`, every release tag and pull request, once a week and when run by hand, and attaches their logs to the run.
Its jobs share [one setup step](../.github/actions/setup/action.yml) that starts from the install an earlier run cached.
GitHub's Windows images include the Visual C++ runtime and other tools a fresh Windows lacks, so a change to what setup downloads or unpacks still needs a check on a fresh Windows.

`node scripts/release-check.mjs` is the release check, which a session runs before cutting a release: what CI runs, on this machine, in about three minutes on Linux.
It runs the build checks and the behavior tests, then the live test, the upgrade test, the previous-release QA check and every scenario CI's workflow lists side by side, each in a private display of its own, and prints one table of what passed and failed with each one's log.
A check that fails is run once more, as the CI flake rule does: one that passes then is reported as a flake, named in the summary with its first log, and a second failure fails the check.
A check that passes leaves only its log; a failed one keeps its folder beside the logs.
`--jobs <n>` sets how many run at once (half the processors, at most 10, by default) and `--work <empty folder>` where they run; like the scenarios, it runs outside a sandbox and downloads the runtimes the live tests install.

The [Windows run](../.github/workflows/windows-run.yml) workflow runs one Bash command after setup on a disposable Windows machine and keeps the logs folders under `$WORK`:

```sh
gh workflow run windows-run.yml -f ref=my-branch -f command='node scripts/scenario.mjs translated --work "$WORK"'
gh run watch "$(gh run list --workflow windows-run.yml --limit 1 --json databaseId -q '.[0].databaseId')"
gh run download <run id> -n logs
```

The ref must be pushed to GitHub, and the workflow file must be on `main` before GitHub offers it.

Wait for a commit's CI with `node scripts/ci-wait.mjs <sha> [--branch <b>]`, never with `gh run watch` or a `gh run list` loop.
Parallel sessions share GitHub's 5,000-call hourly API limit, which those commands exhaust.
The script checks the run's status every 30 s with conditional requests (a 304 is free), follows a newer run when a later push cancels the run, sleeps until the reset when few calls are left, and on a failure prints the failed jobs and the `gh run view --log-failed` command.
It exits 0 when CI passed.
`scripts/release.mjs` waits through the same module.

## Previous-release QA check

`node scripts/qa-upgrade.mjs` checks that a release keeps the [Text QA work](architecture.md#persistence-and-settings) the previous one saved.
It takes the newest release tag other than the checked-out commit's, or `--tag <tag>`, and with that release's code prepares Text QA tasks on two translated copies of the [fixture game](../tests/fixtures/mz-game): one reviewed to the end with a correction and a question not yet applied, and one stopped in deep review.
With this checkout's code and a stand-in detector change, which gives every line one more mechanical flag, the finished task must read complete, be the task preparing QA again returns and apply, undo and apply again; the one in review must go on to the end and apply.
When the checkout's `QA_RULES_VERSION` differs from the release's, the task in review must refuse more review instead, and QA prepares a new one.
The phases run in [qa_upgrade.py](../scripts/qa_upgrade.py), the release's own copy for its tasks when it has one; it needs the release tags (`git fetch --tags`) and the setup's `.venv`, and `--work <empty folder>` keeps its files.
A failure means a change made saved QA work stale: keep what names a task as it was, or bump `QA_RULES_VERSION` when old reviews are wrong now.

## Ace fixture

[tests/fixtures/ace](../tests/fixtures/ace/regenerate.py) rebuilds the VX Ace fixture with Ruby 3.4 and the RV2JSON commit the Ace port follows, neither of which setup installs.
The [Ace fixture workflow](../.github/workflows/ace-fixture.yml) does it and fails when the committed files differ.
It runs on changes to the fixture or the port on `dev`, and by hand, not on every push: `gh workflow run ace-fixture.yml --ref <branch>`, which works once the workflow is on `main`; before that, push a probe branch that adds its name to the workflow's push branches.

## Test scenarios

`node scripts/scenario.mjs <scenario>` builds a known state to reproduce a bug in: a scratch profile and workspace, a copy of a fixture game and a free stand-in provider, never your own profile or games.
It drives this checkout's app through the same steps a user takes, in a private virtual KWin on Linux (or an Xvfb `DISPLAY`, as under `xvfb-run`; never your desktop's), and closes it again; most scenarios build in under 20 seconds.
Run them outside a sandbox such as Claude Code's bwrap: KWin needs a writable `/tmp` and `/dev/dri`, so the scenario stops at once with that advice.
`node scripts/scenario.mjs list` describes each scenario and game variant:

- `fresh`, `opened`, `set-up` and `translated`: the Guided journey up to that point, Live translation applied.
- `update-stopped`: translated, then version 1.1 brought in under Checkpoints, its apply stopped at Git's conflict in a database file the translation changed, as an interrupted update leaves it, so Checkpoints offers to continue or cancel.
- `released`, `released-ace` and `released-mv`: the release journey on MZ, an encrypted VX Ace game and a deployed MV game.
  Translated and applied, a patch ZIP built and its files checked, version 1.1 applied to the end, the files it changed checked Outdated, their new text translated, applied and released again, then that Apply undone in Checkpoints; each fails at the first step that goes wrong.
  Ace's 1.1 is its new `Game.rgss3a` alone, which must read as a patch, and a complete 1.2 is then previewed, which must read as a complete game that removes nothing.
- `qa-done`: Text QA reviewed by a scripted assistant through the project helper, one correction applied.
- `plugins-applied`: `qa-done` on the `plugin-text` game, then its Plugin files translated by a scripted assistant and applied, so Checkpoints holds both applications.
- `moved`: `plugins-applied` with a whole-game estimate and a Text QA task reviewing every line, then the game moved into a `Game` folder inside its own and opened there, then renamed and found with **Find game folder**; each must leave the project, its History, tasks, estimates and saved progress as they were, and preparing Text QA again must go on with the same task, its README naming the game where it is now.
- `moved-relabeled`: `moved`, with the project's engine saved as `Investigation pending` before each step, as versions before 2.33.2 saved it once the old folder was opened again, and the `Game` folder first opened as an empty project; the old project must offer **Find game folder**.
- `assistant-led`: an Assistant-led project in agent mode, set up and organized, its first request translated.
- `assistant-written`: the assistant translates every request and writes them into the game, failing if the write changes the choice labels (402) or help markers (108) the game finds by their Japanese.
- `images`: an Assistant-led project on the `many-images` game, about 4,900 images with 3,400 CGs of about 1 MB, indexed and investigated by the scripted assistant, which recommended the 40 with lettering; for measuring Images on a big game.
- `images-archived`: an Assistant-led project on the `wolf` game, whose pictures sit in `Data/Picture.wolf`; the scripted assistant decodes them with the bundled WolfDawn into a folder the game doesn't read, runs the Images steps on that folder with `images --scan --root`, packs the archive again and checkpoints it, then checks that the patch's archive holds the translated title.
- `batch-waiting`: the database submitted as a Batch that the stand-in holds.
- `batch-queued`: `batch-waiting` with a small Batch token allowance, then a copy of the game Assistant-led whose API Batch on the same OpenAI connection must wait for capacity unsent until the held Batch is released, then be sent and complete.
- `upgraded`: translated by the previous release, then opened in this checkout.
- `paged`: the `long-dialogue` game, translated and applied, then the Line widths narrowed to 24 characters and two rows; fails unless the game shows the long message laid out for them with every word.
  With `--game english-source`, the long message is Japanese, laid out between characters.
- `playtested`: translated, then played by the release playtest, which prints its problems.

`--game` lays [game variants](../tests/fixtures/game-variants) over the MZ fixture game, joined with `+`, such as `--game choice-help+hud+playable`.
`mv` first lays the MZ fixture out as a deployed MV game, its files in `www`; `ace` takes the VX Ace fixture instead, and `ace+encrypted` ships its Data in an encrypted `Game.rgss3a`; `wolf` builds a WOLF RPG Editor game of three pictures in `Data/Picture.wolf`, which takes no variants.
The stand-in's replies are not real translations: it answers any other line with `Tested <letters>` or, for a Japanese target, `テスト` and a run of katakana made from the line's hash, which is why such replies read oddly.
`long-dialogue` adds a traveler whose message the stand-in translates into a long English one, so a scenario can page it at narrow Line widths.
`playable` adds RPG Maker MV's open-source engine, downloaded once into `.runtime`, so the playtest and Text QA's screen captures can run the game.
`--from <ref>` builds the scenario with another commit or tag, from a worktree in `.runtime/checkouts`, such as the commit before a fix: `node scripts/scenario.mjs playtested --from 8ec7da3a` shows the playtest giving a HUD's Japanese the open message's identity.
`--work <dir>` chooses the folder; otherwise it is printed.

`--app` leaves the app running and prints its DevTools and inspector ports and the project helper command; `node scripts/scenario.mjs app --work <dir>` starts it again later.
`node scripts/scenario.mjs drive --work <dir>` with `text`, `click <accessible name>` (the whole name), `click-prefix <start of a name>` (for names ending in something that varies, such as a History row's date), `call <method> <params>`, `eval` or `shot <file>` drives it, and scripts import the same driver from [scripts/testkit/cdp.mjs](../scripts/testkit/cdp.mjs).
`node scripts/scenario.mjs provider --work <dir> '<mode>'` changes how the stand-in answers: the keys it names replace those of its mode and the others stay, such as the game variant's own replies, so `'{"hold":false}'` releases a held Batch. Such as `{"stall":true}`, `{"refuse":["text"]}` or `{"long":["text"]}`, which makes lines holding the text come back as a long English message; [its header](../scripts/testkit/provider.mjs) lists the modes.
`node scripts/scenario.mjs clean --work <dir>` stops every process the scenario started and removes its folder.
`node scripts/scenario.mjs live [--work <dir>] [--upgrade-from <tag>]` runs the [live test](#live-test) in a private KWin of its own.
Scenario connections reach only the stand-in: the custom connection names it, and the OpenAI preset points at it through `DAZEDTL_TEST_OPENAI_ENDPOINT`, which run workers follow too.
Guided and Assistant-led runs on that preset count it as OpenAI's own API ([`native_openai`](../backend/dazedtl/settings/providers.py)), so their Batches wait in the Batch token allowance as on OpenAI.
Phone notifications go to its ntfy stand-in through `DAZEDTL_TEST_NTFY_SERVER`, which keeps them in `provider/phone.jsonl`.
Other requests from the backend and window go to a proxy that is not there; run workers start without proxy settings, so a new provider path needs the run's own address.

To add a scenario, add its steps to [scripts/testkit/scenarios.mjs](../scripts/testkit/scenarios.mjs), reusing the steps there and in [journey.mjs](../scripts/testkit/journey.mjs), and add it to a group of the scenario matrix in [CI's workflow](../.github/workflows/ci.yml); the behavior tests fail while CI leaves a scenario out.
To add a kind of game content, add a folder to [tests/fixtures/game-variants](../tests/fixtures/game-variants) whose `variant.json` describes it; [games.mjs](../scripts/testkit/games.mjs) says what it can change.
The headless playtest runner, the scripted Text QA reviewer, the scripted Plugin files assistant and the scripted Assistant-led assistant sit beside them in [scripts/testkit](../scripts/testkit).

## GameUpdate

[gameupdate](../backend/dazedtl/engine/gameupdate) is the player updater that Set up copies into each game's root folder; [project_preparation.py](../backend/dazedtl/engine/util/project_preparation.py) decides what is copied and which existing files are kept.
Its `README.md` becomes the front page of every published translation repository, so it holds only player instructions; `README.wolf.md` is appended for WOLF games, the only ones that get the bundled UberWolf.
Notes for translators belong in the [user guide](user-guide.md#publishing-with-gameupdate).

In a game, `GameUpdate.bat` and `GameUpdate_linux.sh` find `patch.ps1` and `patch.sh` in the `gameupdate` folder beside them, so they work from any working directory.
Set up also installs `gameupdate/TranslationUpdateCheck.js` as an MV and MZ plugin, the startup check; it records a manually installed update in the same `previous_patch_sha.txt` the scripts use.
Its text for players is in its plugin parameters, which Set up fills from [messages.json](../backend/dazedtl/engine/util/translation_update_check/messages.json) in the game's target language; a language missing there shows the plugin's English defaults, and a value edited in `plugins.js` is kept.
Test updater changes with both `patch.ps1` on Windows and `patch.sh` on Linux; these variables help:

| Environment variable | Purpose |
| --- | --- |
| `GAMEUPDATE_PROMPT_PWSH` | `1` offers to install PowerShell 7 with winget when `GameUpdate.bat` can't find it |
| `GAMEUPDATE_DL_ATTEMPTS` | Attempts for each repository check and download, 2 by default; fewer fail faster, more tolerate flaky networks |

## Branches and releases

Work on `dev`; `main` always holds the latest stable release, so a ZIP of `main` from any mirror is a release.
From a clean `dev`, `node scripts/release.mjs 2.0.1` takes the [landing lock](#landing), runs the tests and build checks, fast-forwards `main` to the `dev` commit CI passed for, sets the version, files the [release notes](#release-notes), signs a manifest of every file, commits and tags `v2.0.1`, pushes `main` and the tag to every mirror and fast-forwards `dev` again.
Run the [release check](#live-test) on that commit first.
Release once user-visible work has landed: the session that finished it cuts the release without asking, with no review pass or manual real-game check, since CI on the release commit runs the release scenarios for MZ, MV and VX Ace on Windows and Linux.
A patch release follows only for a regression players hit.
Before `main` moves, the release requires [CI](#live-test) to have passed on GitHub for that `dev` commit.
It pushes `dev` first when GitHub lacks the commit and waits for a run still in progress; a first failed attempt gets one rerun of its failed jobs, and a second failure or a cancelled run stops the release.
A prerelease such as `2.1.0-beta.1` is tagged on `dev` for the Beta channel instead, without waiting for CI, and `--local` stops before pushing.
The [updater](architecture.md#distribution-and-updates) only accepts tags whose signed manifest matches every file.

The mirrors are listed in [release/mirrors.json](../release/mirrors.json); the release pushes to all of them through one remote:

```sh
git remote add all git@github.com:dazedanon/DazedTL.git
git remote set-url --add --push all git@github.com:dazedanon/DazedTL.git
git remote set-url --add --push all git@ssh.gitgud.io:DazedAnon/dazedtl.git
git remote set-url --add --push all git@git-ssh.dazedtl.dev:dazed/DazedTL.git
```

Releases are signed with a key kept outside the checkout.
Create it once with `node scripts/release.mjs key`, commit the public key it adds to `release/keys`, and back up the private key: installs reject releases signed by any key they do not trust.
Set `DAZEDTL_RELEASE_KEY` to keep the private key somewhere else.

### Landing

`node scripts/land.mjs` lands a finished branch on `dev` from its worktree, on Linux or macOS.
It refuses `dev`, `main` and uncommitted changes, formats the branch with `format.mjs` and commits what that changed as `style: format`, so a landing never fails on formatting alone, then takes the landing lock, the ref `refs/dazedtl/land-lock` in the shared repository, through Git's compare-and-swap ref updates ([land-lock.mjs](../scripts/land-lock.mjs)).
Its holder renews it every five minutes; one whose process has gone, or that nobody renewed for 20 minutes, is taken over.
Under the lock it merges `dev` into the branch, runs the tests and build checks, waits while your own DazedTL runs from the main checkout, and fast-forwards the main checkout's `dev`, which must be checked out there without uncommitted changes to tracked files, never overwriting a file the checkout ignores.
A test run that fails is run once more under the release check's flake rule ([retry.mjs](../scripts/testkit/retry.mjs)), after the machine's load falls to one task per processor or five minutes pass, since other sessions' builds and scenarios can push the suite past its time budget and probe deadlines; a run that passes then is reported as `Flaky:` with the end of the first run, and two failures stop the landing.
It then pushes `dev` to each mirror, trying a refused push again a minute later; a mirror that still refuses is reported and the landing still counts.
A wait on something outside the landing reaches you even while an agent runs it in the background: it tells you once when your DazedTL holds it up and once when that closes, and once when another landing or a release has held the lock for five minutes and once when it gets the lock.
Each of these lines starts with `Notice:` and also shows as a desktop notification where `notify-send` (Linux) or `osascript` (macOS) exists.
A last line says how long it took, in total and per stage (format, lock wait, merge, test, build, push), so a slow landing shows where the time went.
In the merge, both sides' [release notes](#release-notes) join under their headings through [changelog.mjs](../scripts/changelog.mjs), and conflicts only in the [generated API contracts](architecture.md#api-changes) are resolved by writing them again.
Any other conflict stops it with exit code 2 and leaves the merge in progress with everything else merged, so you resolve only the listed files, commit and land again; a merge started again by hand would merge the notes as text.

[CI](#live-test) runs on `dev` after the push, not on the branch; the landing warns when `dev`'s newest run failed but does not wait for CI.
A run still red is fixed forward or reverted by the session cutting the next release, whose `release.mjs` reruns it once first and holds the landing lock throughout.
To run CI on a branch before landing, use `gh workflow run CI --ref <branch>` and wait with `ci-wait.mjs`.

### Release notes

Every stable release needs notes for users, and `release.mjs` stops until [release/notes.md](../release/notes.md) has them.
Write them just before releasing, from `git log` since the last tag, under the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) headings `### Added`, `Changed`, `Deprecated`, `Removed`, `Fixed` and `Security`, one `- ` line per change:

```markdown
### Fixed

- **Set up:** saving the game's first version no longer stops with "Bundled GameUpdate .gitignore is unavailable".
```

- Start with where it happens, in bold: **Set up**, **Progress**, **Assistant-led**, **GameUpdate**, **Settings**.
- Say what the user sees, in the app's own words, never internal names such as census, helper or baseline.
- For a fix, name the old symptom so people recognize it, and quote an error only if users saw it.
- Merge related commits into one line and leave out changes nobody would notice.

The release moves the notes into [CHANGELOG.md](../CHANGELOG.md) under the version and date, links the version to its changes on GitHub, empties `release/notes.md` and uses the notes as the tag message.
A prerelease leaves them pending, and the app shows a beta's pending notes as that version's.
Never edit `CHANGELOG.md` by hand; [changelog.mjs](../scripts/changelog.mjs) reads and writes it.

## Not yet verified

- The macOS launcher has not been run on macOS yet; the [live test](#live-test) covers Windows and Linux.
- Real provider billing and native game playtesting still need validation.

## Documentation

- The [user guide](user-guide.md) explains the app's workflows, API setup, backups and diagnostics.
- [Architecture](architecture.md) covers code ownership, boundaries and design decisions.
- The [translation contract](translation-contract.md) is for engine adapter authors and assistant integrations.
- The [text QA redesign](text-qa-redesign.md) plans the next version of text QA.
- [AGENTS.md](../AGENTS.md) holds contribution rules.
