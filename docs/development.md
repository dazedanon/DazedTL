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
The runner reports the five slowest Python tests to make runtime regressions visible.
If Python is still running a second before the budget ends, it prints every thread's stack, which names the test and line it waits on.
Tests use temporary workspaces and controlled API responses; no provider, game folder or credentials are needed.

For focused iteration, use `.venv/bin/python -I -B -m unittest discover -s tests -t . -p test_projects.py` or `node --test --test-isolation=none tests/application.test.ts` from the root.
Run `node scripts/build.mjs` separately for static checks and the renderer build.
It checks formatting, that stylesheets use the [design tokens](architecture.md#visual-design), that the [generated API contracts](architecture.md#api-changes) are current and that tracked paths fit the [Windows path budget](architecture.md#distribution-and-updates).
It lints with type-aware [Oxlint](../.oxlintrc.json) (including the React hooks rules) and [Ruff](../pyproject.toml), and type-checks the renderer, the Electron main process and DazedTL-owned Python with [Pyright](../pyproject.toml).
Of the bundled engine, only Text QA ([util/qa](../backend/dazedtl/engine/util/qa/__init__.py)) gets the same Ruff rules, through its own [settings](../backend/dazedtl/engine/util/qa/ruff.toml), and Pyright.
Ruff also rejects file and process calls that go around the [platform layer](../backend/dazedtl/system.py), in the bundled engine too through its own [settings](../backend/dazedtl/engine/ruff.toml), and text files opened without an encoding.
Launching builds a missing renderer without these checks.
Format with `node scripts/format.mjs`; it applies Prettier and Ruff defaults and leaves the bundled engine, Markdown and JSON unchanged.

## Live test

`node scripts/e2e.mjs` installs the checkout the way a user's downloaded ZIP is installed and drives the running app through a translation.
It copies the files Git would commit, including uncommitted changes, into a doubled `DazedTL-main (1)` folder and runs START with a PATH that has no Node or Python, and on Windows no Git.
The profile and a copy of the [fixture game](../tests/fixtures/mz-game) sit in folders with spaces and Japanese names; the copy takes the `event-text` and `choice-help` [game variants](#test-scenarios), so Comment text comes on for the menu's choice help.
Through the window it opens the game, runs Set up, translates and applies the database and the maps with Live translation against a local stand-in provider, stands in for the assistant's Event text sources investigation and translates and applies Other event text, opens Check and runs the Text QA assistant's playtest through the project helper, which checks the files and reports that the fixture game has no engine to play, and builds a patch ZIP.
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

[CI](../.github/workflows/ci.yml) runs the build checks, the behavior tests, the [previous-release QA check](#previous-release-qa-check), the live test, the upgrade test from the latest earlier stable release and every [test scenario](#test-scenarios) on Windows and Linux for every pushed branch, every pull request and once a week, and attaches their logs to the run.
Its jobs share [one setup step](../.github/actions/setup/action.yml) that starts from the install an earlier run cached.
GitHub's Windows images include the Visual C++ runtime and other tools a fresh Windows lacks, so a change to what setup downloads or unpacks still needs a check on a fresh Windows.

The [Windows run](../.github/workflows/windows-run.yml) workflow runs one Bash command after setup on a disposable Windows machine and keeps the logs folders under `$WORK`:

```sh
gh workflow run windows-run.yml -f ref=my-branch -f command='node scripts/scenario.mjs translated --work "$WORK"'
gh run watch "$(gh run list --workflow windows-run.yml --limit 1 --json databaseId -q '.[0].databaseId')"
gh run download <run id> -n logs
```

The ref must be pushed to GitHub, and the workflow file must be on `main` before GitHub offers it.

## Previous-release QA check

`node scripts/qa-upgrade.mjs` checks that a release keeps the [Text QA work](architecture.md#persistence-and-settings) the previous one saved.
It takes the newest release tag other than the checked-out commit's, or `--tag <tag>`, and with that release's code prepares Text QA tasks on two translated copies of the [fixture game](../tests/fixtures/mz-game): one reviewed to the end with a correction and a question not yet applied, and one stopped in deep review.
With this checkout's code and a stand-in detector change, which gives every line one more mechanical flag, the finished task must read complete, be the task preparing QA again returns and apply, undo and apply again; the one in review must go on to the end and apply.
When the checkout's `QA_RULES_VERSION` differs from the release's, the task in review must refuse more review instead, and QA prepares a new one.
The phases run in [qa_upgrade.py](../scripts/qa_upgrade.py), the release's own copy for its tasks when it has one; it needs the release tags (`git fetch --tags`) and the setup's `.venv`, and `--work <empty folder>` keeps its files.
A failure means a change made saved QA work stale: keep what names a task as it was, or bump `QA_RULES_VERSION` when old reviews are wrong now.

## Test scenarios

`node scripts/scenario.mjs <scenario>` builds a known state to reproduce a bug in: a scratch profile and workspace, a copy of a fixture game and a free stand-in provider, never your own profile or games.
It drives this checkout's app through the same steps a user takes, in a private virtual KWin on Linux (or an Xvfb `DISPLAY`, as under `xvfb-run`; never your desktop's), and closes it again; most scenarios build in under 20 seconds.
`node scripts/scenario.mjs list` describes each scenario and game variant:

- `fresh`, `opened`, `set-up` and `translated`: the Guided journey up to that point, Live translation applied.
- `qa-done`: Text QA reviewed by a scripted assistant through the project helper, one correction applied.
- `assistant-led`: an Assistant-led project in agent mode, set up and organized, its first request translated.
- `batch-waiting`: the database submitted as a Batch that the stand-in holds.
- `upgraded`: translated by the previous release, then opened in this checkout.
- `playtested`: translated, then played by the release playtest, which prints its problems.

`--game` lays [game variants](../tests/fixtures/game-variants) over the MZ fixture game, joined with `+`, such as `--game choice-help+hud+playable`; `ace` takes the VX Ace fixture instead.
`playable` adds RPG Maker MV's open-source engine, downloaded once into `.runtime`, so the playtest and Text QA's screen captures can run the game.
`--from <ref>` builds the scenario with another commit or tag, from a worktree in `.runtime/checkouts`, such as the commit before a fix: `node scripts/scenario.mjs playtested --from 8ec7da3a` shows the playtest giving a HUD's Japanese the open message's identity.
`--work <dir>` chooses the folder; otherwise it is printed.

`--app` leaves the app running and prints its DevTools and inspector ports and the project helper command; `node scripts/scenario.mjs app --work <dir>` starts it again later.
`node scripts/scenario.mjs drive --work <dir>` with `text`, `click <accessible name>`, `call <method> <params>`, `eval` or `shot <file>` drives it, and scripts import the same driver from [scripts/testkit/cdp.mjs](../scripts/testkit/cdp.mjs).
`node scripts/scenario.mjs provider --work <dir> '<mode>'` changes how the stand-in answers, such as `{"stall":true}` or `{"refuse":["text"]}`; [its header](../scripts/testkit/provider.mjs) lists the modes.
`node scripts/scenario.mjs clean --work <dir>` stops every process the scenario started and removes its folder.
`node scripts/scenario.mjs live [--work <dir>] [--upgrade-from <tag>]` runs the [live test](#live-test) in a private KWin of its own.
Scenario connections reach only the stand-in: the custom connection names it, and the OpenAI preset points at it through `DAZEDTL_TEST_OPENAI_ENDPOINT`, which run workers follow too.
Other requests from the backend and window go to a proxy that is not there; run workers start without proxy settings, so a new provider path needs the run's own address.

To add a scenario, add its steps to [scripts/testkit/scenarios.mjs](../scripts/testkit/scenarios.mjs), reusing the steps there and in [journey.mjs](../scripts/testkit/journey.mjs).
To add a kind of game content, add a folder to [tests/fixtures/game-variants](../tests/fixtures/game-variants) whose `variant.json` describes it; [games.mjs](../scripts/testkit/games.mjs) says what it can change.
The headless playtest runner, the scripted Text QA reviewer and the scripted Assistant-led assistant sit beside them in [scripts/testkit](../scripts/testkit).

## GameUpdate

[gameupdate](../backend/dazedtl/engine/gameupdate) is the player updater that Set up copies into each game's root folder; [project_preparation.py](../backend/dazedtl/engine/util/project_preparation.py) decides what is copied and which existing files are kept.
Its `README.md` becomes the front page of every published translation repository, so it holds only player instructions; `README.wolf.md` is appended for WOLF games, the only ones that get the bundled UberWolf.
Notes for translators belong in the [user guide](user-guide.md#publishing-with-gameupdate).

In a game, `GameUpdate.bat` and `GameUpdate_linux.sh` find `patch.ps1` and `patch.sh` in the `gameupdate` folder beside them, so they work from any working directory.
Set up also installs `gameupdate/TranslationUpdateCheck.js` as an MV and MZ plugin, the startup check; it records a manually installed update in the same `previous_patch_sha.txt` the scripts use.
Test updater changes with both `patch.ps1` on Windows and `patch.sh` on Linux; these variables help:

| Environment variable | Purpose |
| --- | --- |
| `GAMEUPDATE_PROMPT_PWSH` | `1` offers to install PowerShell 7 with winget when `GameUpdate.bat` can't find it |
| `GAMEUPDATE_DL_ATTEMPTS` | Attempts for each repository check and download, 2 by default; fewer fail faster, more tolerate flaky networks |

## Branches and releases

Work on `dev`; `main` always holds the latest stable release, so a ZIP of `main` from any mirror is a release.
From a clean `dev`, `node scripts/release.mjs 2.0.1` runs the tests and build checks, fast-forwards `main` to `dev`, sets the version, files the [release notes](#release-notes), signs a manifest of every file, commits and tags `v2.0.1`, pushes `main` and the tag to every mirror and fast-forwards `dev` again.
Before `main` moves, the release requires [CI](#live-test) to have passed on GitHub for that `dev` commit.
It pushes `dev` first when GitHub lacks the commit and waits for a run still in progress; a failed or cancelled run stops the release.
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
