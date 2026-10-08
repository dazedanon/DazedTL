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
The scripts run on any Node release within the pinned major version.
After changing either version file, run `node scripts/runtimes.mjs` to pin the new downloads in [runtimes.lock](../scripts/runtimes.lock).

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
The runner reports the five slowest Python tests to make runtime regressions visible.
Tests use temporary workspaces and controlled API responses; no provider, game folder or credentials are needed.

For focused iteration, use `.venv/bin/python -I -B -m unittest discover -s tests -t . -p test_projects.py` or `node --test --test-isolation=none tests/application.test.ts` from the root.
Run `node scripts/build.mjs` separately for static checks and the renderer build.
It checks formatting, that stylesheets use the [design tokens](architecture.md#visual-design), that the [generated API contracts](architecture.md#api-changes) are current and that tracked paths fit the [Windows path budget](architecture.md#distribution-and-updates).
It lints with type-aware [Oxlint](../.oxlintrc.json) (including the React hooks rules) and [Ruff](../ruff.toml), and type-checks the renderer, the Electron main process and DazedTL-owned Python with [Pyright](../pyrightconfig.json).
Launching builds a missing renderer without these checks.
Format with `node scripts/format.mjs`; it applies Prettier and Ruff defaults and leaves the bundled engine, Markdown and JSON unchanged.

## Branches and releases

Work on `dev`; `main` always holds the latest stable release, so a ZIP of `main` from any mirror is a release.
From a clean `dev`, `node scripts/release.mjs 2.0.1` runs the tests and build checks, fast-forwards `main` to `dev`, sets the version, signs a manifest of every file, commits and tags `v2.0.1`, pushes `main` and the tag to every mirror and fast-forwards `dev` again.
A prerelease such as `2.1.0-beta.1` is tagged on `dev` for the Beta channel instead, and `--local` stops before pushing.
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

## Not yet verified

- The Windows and macOS launchers and Windows shortcuts have not been run on those systems yet.
- Real provider billing and native game playtesting still need validation.

## Documentation

- The [user guide](user-guide.md) explains the app's workflows, API setup, backups and diagnostics.
- [Architecture](architecture.md) covers code ownership, boundaries and design decisions.
- The [translation contract](translation-contract.md) is for engine adapter authors and assistant integrations.
- [AGENTS.md](../AGENTS.md) holds contribution rules.
