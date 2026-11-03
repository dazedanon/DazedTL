# Development

Working on DazedTL: setup, checks, test scenarios and releases.
[AGENTS.md](../AGENTS.md) holds the contribution rules, and [architecture](architecture.md) how the code is organized.

## Setup

```sh
node scripts/setup.mjs
node scripts/build.mjs
node scripts/start.mjs
```

- `setup.mjs` installs the pinned Python, the locked packages (with the format, lint and type-check tools) and Electron into `.runtime`, `.venv` and `app/node_modules`.
  On Windows it also installs portable Git; other systems need their own `git`.
- `start.mjs` keeps the app attached to the terminal, and `--offline` disables provider calls.
  Like the `START` launchers, it repeats a setup step only when its inputs change.
- The pinned versions are in [python-version](../scripts/python-version), [node-version](../scripts/node-version) and [mingit-version](../scripts/mingit-version); after changing one, run `node scripts/runtimes.mjs`.
- The app keeps projects, credentials and runs in the `DazedTL2` profile, under `%APPDATA%` on Windows and `~/.config` on Linux.

| Environment variable | Purpose |
| --- | --- |
| `DAZEDTL_PYTHON` | A Python with the backend's packages, used instead of the pinned one |
| `DAZEDTL_PROFILE` | Electron profile location |
| `DAZEDTL_WORKSPACE` | Project and run storage location |

## Checks

| Command | What it does |
| --- | --- |
| `node scripts/test.mjs` | Runs every behavior test, Python and Node, within a 10-second budget |
| `node scripts/build.mjs` | Checks formatting, lint (Oxlint, Ruff), types (Pyright, TypeScript), design tokens, generated API contracts, Windows path lengths and document word limits, then builds the renderer |
| `node scripts/format.mjs` | Formats the code with Prettier and Ruff, leaving the bundled engine, Markdown and JSON alone |

To run one test module:

```sh
.venv/bin/python -I -B -m unittest discover -s tests -t . -p test_projects.py
node --test --test-isolation=none tests/application.test.ts
```

- Tests are hermetic: temporary workspaces and controlled API responses, with no provider, game or credentials.
- The budget covers startup and teardown; `DAZEDTL_TEST_BUDGET` sets another in seconds, as CI does for its slower runners.
  Near the end, the runner prints where Python is waiting; [tests/run.py](../tests/run.py) explains how it schedules modules.
- Python test modules share worker interpreters, so a test that replaces modules in `sys.modules` uses `replaced_modules` from [tests/engine.py](../tests/engine.py).
- Ruff and [platform_calls](../scripts/platform_calls.py) reject file and process calls that go around the [platform layer](../backend/dazedtl/system.py), and text files opened without an encoding.

### Thinking effort table

[effort.py](../backend/dazedtl/settings/effort.py) lists the thinking effort levels each provider's models take, each row dated when it was last confirmed against the real API.
When you add a model or level, or a provider changes its effort parameters, confirm it with `.venv/bin/python scripts/effort_check.py [--provider NAME]`.
It reads the keys from the environment, prints what it would send and its cost cap, and sends nothing without `--confirm`; it never runs in tests or CI.

## Live test

`node scripts/e2e.mjs` installs this checkout the way a user's downloaded ZIP is installed and drives the app through a Guided translation against a local stand-in provider; [its header](../scripts/e2e.mjs) lists what it checks.
`--upgrade-from <tag>`, or `previous` for the latest stable release, instead updates an install of that release to this checkout, and `--work <empty folder>` keeps its logs, screenshots and diagnostics.

On Linux it needs a display: CI runs it under `xvfb-run`, and on a desktop `node scripts/scenario.mjs live [--upgrade-from <tag>]` runs it in a private KWin, off your screen.

## CI

[CI](../.github/workflows/ci.yml) runs the build checks, the behavior tests, the [previous-release QA check](#previous-release-qa-check), the live test, the upgrade test and every [test scenario](#test-scenarios) on Windows and Linux, for every push to `dev` and `main`, release tag and pull request, weekly and by hand.

- **Wait for a commit's CI** with `node scripts/ci-wait.mjs <sha> [--branch <b>]`, never `gh run watch` or a `gh run list` loop: parallel sessions share GitHub's hourly API limit, which those use up.
- **Run what CI runs locally** with `node scripts/release-check.mjs`, in about three minutes on Linux, outside a sandbox.
  A check that fails runs once more, and one that passes then is reported as a flake.
- **Run CI on a branch** before landing with `gh workflow run CI --ref <branch>`.

Reproduce a Windows problem first on a disposable Windows machine with the [Windows run](../.github/workflows/windows-run.yml) workflow, from a ref pushed to GitHub:

```sh
gh workflow run windows-run.yml -f ref=my-branch -f command='node scripts/scenario.mjs translated --work "$WORK"'
gh run watch "$(gh run list --workflow windows-run.yml --limit 1 --json databaseId -q '.[0].databaseId')"
gh run download <run id> -n logs
```

GitHub's Windows images include the Visual C++ runtime and other tools a fresh Windows lacks, so keep the Windows VM for a fresh Windows, Defender and real games.

## Test scenarios

`node scripts/scenario.mjs <scenario>` builds a known state to reproduce a bug or test a feature in: a scratch profile and workspace, a copy of a fixture game and a free stand-in provider, never your own.
It drives the app as a user does, in a private display, and most scenarios build in under 20 seconds.

- `node scripts/scenario.mjs list` describes every scenario and game variant, and `--help` shows the options.
- Run it outside a sandbox such as Claude Code's, since KWin needs a writable `/tmp` and `/dev/dri`.
- `--game` lays [game variants](../tests/fixtures/game-variants) over the fixture game, joined with `+`, such as `--game choice-help+playable`; `--from <ref>` builds with another commit, such as the one before a fix.
- `--app` leaves the app running for `drive --work <dir>`, which reads, clicks and screenshots it (scripts import the same driver from [cdp.mjs](../scripts/testkit/cdp.mjs)); `clean --work <dir>` stops it and removes the folder.
- The stand-in's replies aren't real translations: it answers most lines with `Tested <letters>`.
  `provider --work <dir> '<mode JSON>'` changes how it answers, such as `'{"hold":false}'` to release a held Batch; [its header](../scripts/testkit/provider.mjs) lists the modes, and it records each request in `provider/requests.jsonl`.
- Scenarios never reach a real provider: the OpenAI, Anthropic, OpenRouter and both OpenCode presets follow `DAZEDTL_TEST_*_ENDPOINT` variables to the stand-in ([providers.py](../backend/dazedtl/settings/providers.py)), and phone notifications follow `DAZEDTL_TEST_NTFY_SERVER`.
  A new provider path needs such a variable too.

To add a scenario, add its steps to [scenarios.mjs](../scripts/testkit/scenarios.mjs), reusing those there and in [journey.mjs](../scripts/testkit/journey.mjs), and add it to the scenario matrix in [CI's workflow](../.github/workflows/ci.yml); the behavior tests fail while CI leaves one out.
To add game content, add a folder with a `variant.json` to [tests/fixtures/game-variants](../tests/fixtures/game-variants); [games.mjs](../scripts/testkit/games.mjs) says what a variant can change.

## Previous-release QA check

`node scripts/qa-upgrade.mjs` checks that the Text QA tasks the previous release saved, one finished and one still in review, continue, finish and apply with this checkout's code; it needs the release tags (`git fetch --tags`).
A failure means a change made saved QA work stale: keep what names a task as it was, or bump `QA_RULES_VERSION` in [qa/schema](../backend/dazedtl/engine/util/qa/schema.py) when old reviews are now wrong.

## Ace fixture

[regenerate.py](../tests/fixtures/ace/regenerate.py) rebuilds the VX Ace fixture with Ruby 3.4 and RV2JSON, which setup doesn't install.
The [Ace fixture workflow](../.github/workflows/ace-fixture.yml) runs it when the fixture or the Ace port changes on `dev` and fails when the committed files differ; run it on a branch with `gh workflow run ace-fixture.yml --ref <branch>`.

## README media

`node scripts/media.mjs` retakes the README's screenshots and animation in [docs/media](media); run it when a screen they show changes.
It needs ffmpeg with libwebp and runs outside a sandbox, like the scenarios; `--keep` leaves the app running.
Keep the files small, since every user downloads them with each update: WebP stills 1760 pixels wide, the animation 1280.
It also makes the link card [resources/social-preview.jpg](../resources/social-preview.jpg); when that changes, upload it again in the GitHub repository's Settings > Social preview.

## Quality measurement

A change that shapes translated text is judged by what Text QA has to correct.
[qa_corrections.py](../backend/dazedtl/engine/scripts/qa_corrections.py) counts that from finished games' QA records, which it only reads:

```sh
.venv/bin/python backend/dazedtl/engine/scripts/qa_corrections.py report <profile>/workspace/engine/workflows <game folder>...
.venv/bin/python backend/dazedtl/engine/scripts/qa_corrections.py export <same targets> --out <file outside the games and this checkout>
```

`report` prints each game's corrections per 1,000 translated lines by kind, such as glossary, meaning or fluency, and the fixes that recur most; `export` writes them as the dataset regression sets are built from.
[util/qa_corrections.py](../backend/dazedtl/engine/util/qa_corrections.py) defines the kinds, the counting unit and the export.
A hand check of 73 corrections across 8 games found 68 kinds right, and the rules now fix 4 of the 5 misses; no check has measured whether QA's findings are real errors.

### Comparing a change

No change waits on a paid comparison to land: a change that shapes translated text lands on its own checks, such as each request carrying what the change adds and replies parsing as before.
The comparison detects only differences of roughly 10 points, so run it only when the user chooses to measure a decision that touches every request, such as the default model, the effort level or a prompt file, and only with the user's OK and a cap for each paid run (the user's decision of 2026-10-28).

[quality_compare.py](../backend/dazedtl/engine/scripts/quality_compare.py) builds the set, estimates, translates and compares; keep its files outside this checkout, since they hold game text:

```sh
q=backend/dazedtl/engine/scripts/quality_compare.py
.venv/bin/python $q build-set --export <export> --out <set>
.venv/bin/python $q estimate --set <set> [--targeted <items>] --variant <variant.json> --judge <judge.json>
printf %s "$KEY" | .venv/bin/python $q translate --set <set> [--targeted <items>] --variant <baseline.json> --runs <runs> --run-id base-1 --cap <dollars> --key-stdin --wait
# again as base-2, then the change's variant as change-1
printf %s "$KEY" | .venv/bin/python $q compare --set <set> [--targeted <items>] --runs <runs> --baseline base-1 base-2 --variant-run change-1 --judge <judge.json> --compare-id <name> --cap <dollars> --key-stdin --wait
```

- The [regression set](../backend/dazedtl/engine/util/quality_set.py) holds about 300 lines QA corrected and 300 it passed, each with the context its request sent, split once into a tune half and a held-out half; its docstring describes the set and the targeted item files a change can add.
- A variant names the method, connection, prompt file and context switches; [evaluation_quality](../backend/dazedtl/engine/util/evaluation_quality.py)'s `variant` and `judge` validate them, and its docstring explains runs and comparisons.
- The judge's calibration takes QA's findings as true, and the defect judge sees the reviewer's description of the draft it must flag, so its separation is an upper bound; a change counts only beyond the gap between the baseline's two runs.

## GameUpdate

[gameupdate](../backend/dazedtl/engine/gameupdate) is the player updater Set up copies into each game; [project_preparation.py](../backend/dazedtl/engine/util/project_preparation.py) decides what is copied and which existing files are kept.
Its `README.md` becomes the front page of every published translation repository, so it holds only player instructions; notes for translators belong in the [user guide](user-guide.md#publishing-with-gameupdate).
The MV and MZ startup check, `TranslationUpdateCheck.js`, shows players text from [messages.json](../backend/dazedtl/engine/util/translation_update_check/messages.json) in the game's target language.

Test updater changes with both `patch.ps1` on Windows and `patch.sh` on Linux.
`GAMEUPDATE_PROMPT_PWSH=1` offers to install PowerShell 7 when `GameUpdate.bat` can't find it, and `GAMEUPDATE_DL_ATTEMPTS` sets the attempts for each download, 2 by default.

## Branches and releases

Work on `dev`; `main` always holds the latest stable release, so a ZIP of `main` from any mirror is a release.

### Contributing a change

1. Fork DazedTL on any mirror in [mirrors.json](../release/mirrors.json) and branch from `dev`.
2. Follow [Setup](#setup), make the change with its test as [AGENTS.md](../AGENTS.md) says, and run the [checks](#checks).
3. Open a pull request against `dev` on that mirror.

A fix you found in a game but didn't code can go through the guide's [Share a fix](user-guide.md#contributing) instead.

### Landing

`node scripts/land.mjs --review <file.json>` lands a finished branch on `dev` from its worktree: it formats the branch, merges `dev` into it, runs the tests and build checks, fast-forwards the main checkout's `dev` and pushes it to every mirror.
One landing runs at a time, under a lock that a release also holds.

- The review record says which `code-review` level ran and whether each finding was fixed or dismissed, with a reason, or why no review ran; [readReview](../scripts/land.mjs) gives its shape.
  Each landed record joins `dazedtl-reviews.jsonl` in the shared Git directory with its branch and range, to show whether reviews catch enough to become a gate.
- A failed test run runs once more after the machine's load drops; a pass then is reported as `Flaky:`, and a second failure stops the landing.
- Both sides' [release notes](#release-notes) are joined, and conflicts only in the generated API contracts are resolved by writing them again.
  A branch that repeats a notes line `dev` already released stops on `release/notes.md`: keep only what's new.
- Any other conflict stops it with exit code 2 and the merge in progress: resolve the listed files, commit and land again.
- Lines starting with `Notice:`, also shown as desktop notifications, say when your own DazedTL or another landing holds it up.
- CI runs on `dev` after the push; a run still red is fixed forward or reverted by the session cutting the next release.

### Releasing

From a clean `dev`, once the [release check](#ci) passes on that commit:

```sh
node scripts/release.mjs 2.0.1
```

It waits for CI to pass on GitHub for that `dev` commit, rerunning failed jobs once, then fast-forwards `main`, files the [release notes](#release-notes), signs a manifest of every file, tags `v2.0.1`, pushes `main` and the tag to every mirror and publishes the notes as the tag's GitHub Release.
If only the GitHub Release fails, `node scripts/release.mjs github 2.0.1` publishes it from the tag.
A prerelease such as `2.1.0-beta.1` is tagged on `dev` for the Beta channel without waiting for CI, and `--local` stops before pushing.

Release once user-visible work has landed: the session that finished it cuts the release without asking, with no review pass or manual real-game check, since CI on the release commit runs the release scenarios for MZ, MV and VX Ace.
A patch release follows only for a regression players hit.

The release pushes to the mirrors in [release/mirrors.json](../release/mirrors.json) through one remote:

```sh
git remote add all git@github.com:dazedanon/DazedTL.git
git remote set-url --add --push all git@github.com:dazedanon/DazedTL.git
git remote set-url --add --push all git@ssh.gitgud.io:DazedAnon/dazedtl.git
git remote set-url --add --push all git@git-ssh.dazedtl.dev:dazed/DazedTL.git
```

Releases are signed with the maintainer's key, kept outside the checkout; `DAZEDTL_RELEASE_KEY` sets another location.
The [updater](architecture.md#distribution-and-updates) accepts only releases signed by a key in [release/keys](../release/keys), so restore a missing key from its backup: `release.mjs key` makes a new key that no install trusts, which only a fork needs.

### Release notes

Every stable release needs notes for users in [release/notes.md](../release/notes.md), and `release.mjs` stops until they're there.
Write them just before releasing, from `git log` since the last tag, under the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) headings `### Added`, `Changed`, `Deprecated`, `Removed`, `Fixed` and `Security`, one `- ` line per change:

```markdown
### Fixed

- **Set up:** saving the game's first version no longer stops with "Bundled GameUpdate .gitignore is unavailable".
```

- Start with where it happens, in bold, such as **Set up**, **Progress** or **Settings**.
- Say what the user sees, in the app's own words, never internal names such as census, helper or baseline.
- For a fix, name the old symptom so people recognize it, and quote an error only if users saw it.
- Merge related commits into one line, and leave out changes nobody would notice.

The release moves the notes into [CHANGELOG.md](../CHANGELOG.md) under the version, which [changelog.mjs](../scripts/changelog.mjs) writes, so never edit it by hand.
A prerelease leaves them pending, and the app shows a beta's pending notes as that version's.

## Not yet verified

- The macOS launcher has not been run on macOS.
- Real provider billing and native game playtesting still need validation.

## Documentation

Each document serves one reader: write what that reader needs to act, and link to the code or a script's `--help` for the rest.
The build holds each document to its word limit in [docs.mjs](../scripts/docs.mjs).

- The [README](../README.md) is the landing page, for people who use AI but can't program: what DazedTL does, shown with the [README media](#readme-media), then installing, getting started and current limits.
- The [user guide](user-guide.md) tells users how to do each task, in a few lines each.
  The app's **Guide** page shows it, so a renamed heading also renames the anchor that help's Learn more links name, which the guide tests check.
  What the app already says on screen stays out: errors and edge cases, recovery offers and each option's help.
  A change adds to it only when it adds a task or changes what the user does.
- This development guide says which command to run when, and the rules around it; a script's options and details belong in its header and `--help`.
- [Architecture](architecture.md) covers code ownership, boundaries and design decisions.
- The [translation contract](translation-contract.md) is for engine adapter authors and assistant integrations.
- The [text QA redesign](text-qa-redesign.md) plans the next version of Text QA.
- [AGENTS.md](../AGENTS.md) holds the contribution rules.
