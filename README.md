# DazedTL

DazedTL is a desktop app for translating games with its bundled translation engine.
RPG Maker MV/MZ and Ace games use a guided five-stage workflow, and Assistant-led, built on Len's game-translation skills, lets a coding assistant translate any game through the running app.
The [user guide](docs/user-guide.md) covers both workflows.

## Install

1. Download the ZIP of the latest release from [GitHub](https://github.com/dazedanon/DazedTL), [GitGud](https://gitgud.io/DazedAnon/DazedTL) or [git.dazedtl.dev](https://git.dazedtl.dev/dazed/DazedTL), and unpack it into its own folder.
2. Run `START.bat` on Windows or `START.sh` on Linux; macOS has `START.command`.

Nothing needs to be installed first.
The first start downloads about 300 MB, the pinned Node and Python, the locked Python and Node packages and Electron, and takes a few minutes.
Everything installs inside the DazedTL folder, and the first start adds DazedTL to the Start menu and desktop on Windows, or to the application menu on Linux.
The console shows progress and closes once the app opens; later starts open the app directly.
A moved folder repairs its Python environment and shortcuts on its next start.

On Ubuntu 24.04 and later, the first start prints a one-time `sudo` command that lets the app use its browser sandbox; run it, then start again.

Projects, credentials and runs live outside the DazedTL folder, in the `DazedTL2` profile in the system's application data folder (`%APPDATA%` on Windows, `~/.config` on Linux), separate from DazedMTLTool.
An existing pre-release `DazedTLNext` profile keeps being used.

## Current limitations

- WOLF's guided workflow is deferred; other engines are supported only through Assistant-led.
- Real provider billing and native game playtesting still need validation.
- The Windows and macOS launchers and Windows shortcuts have not been run on those systems yet.

## Development

The checkout includes its engine code, worker helpers, tokenizers, native tools and translation toolkit; no DazedMTLTool installation or sibling engine checkout is required.
See [resource ownership](docs/architecture.md#ownership) for the engine and shared prompt locations, saved-run compatibility and override behavior.

```sh
node scripts/setup.mjs
node scripts/build.mjs
node scripts/start.mjs
```

Setup installs the pinned Python from [.python-version](.python-version), the locked packages including the formatting, lint and type-check tools, and Electron into `.runtime`, `.venv` and `app/node_modules`.
It runs npm from the pinned Node in [.node-version](.node-version), downloading it on Linux and macOS; on Windows it uses the Node that runs it until `START.bat` has installed the pinned one.
The scripts run on any Node release within the pinned major version.
After changing either version file, run `node scripts/runtimes.mjs` to pin the new downloads in [runtimes.lock](scripts/runtimes.lock).

`node scripts/start.mjs` keeps the app attached to the terminal; `START` launchers detach it.
Both repeat a setup step only when its inputs change and rebuild a stale interface.
Use `node scripts/start.mjs --offline` to inspect the UI with provider execution disabled.

| Optional environment variable | Purpose |
| --- | --- |
| `DAZEDTL_PYTHON` | Python executable with backend dependencies; setup creates `.venv` from it instead of the pinned Python |
| `DAZEDTL_PROFILE` | Electron profile location |
| `DAZEDTL_WORKSPACE` | Project and run storage location |

## Development checks

Run the full behavior suite from this checkout with `node scripts/test.mjs` (or `npm test` from `app`).
It uses the local Python environment and Node's built-in test runner, with one enforced wall-clock budget including startup, fixtures, and teardown.
The runner reports the five slowest Python tests to make runtime regressions visible.
Tests use temporary workspaces and controlled API responses; no provider, game folder, credentials, or sibling checkout is needed.

For focused iteration, use `.venv/bin/python -I -B -m unittest discover -s tests -t . -p test_projects.py` or `node --test --test-isolation=none tests/application.test.ts` from the root.
Run `node scripts/build.mjs` separately for static checks and the renderer build.
It checks formatting, that stylesheets use the [design tokens](docs/architecture.md#visual-design) that the [generated API contracts](docs/architecture.md#api-changes) are current and that tracked paths fit the [Windows path budget](docs/architecture.md#distribution-and-updates), lints with type-aware [Oxlint](.oxlintrc.json) (including the React hooks rules) and [Ruff](ruff.toml), and type-checks the renderer, the Electron main process and DazedTL-owned Python with [Pyright](pyrightconfig.json).
Launching builds a missing renderer without these checks.
Format with `node scripts/format.mjs`; it applies Prettier and Ruff defaults and leaves the bundled engine, Markdown and JSON unchanged.
To skip the one-time formatting commit in local `git blame`, run `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

## Documentation

- The [user guide](docs/user-guide.md) explains the app's workflows, API setup, backups and diagnostics.
- [Architecture](docs/architecture.md) covers code ownership, boundaries and design decisions.
- The [translation contract](docs/translation-contract.md) is for engine adapter authors and assistant integrations.
- [AGENTS.md](AGENTS.md) holds contribution rules.
- The [migration record](docs/migration.md) keeps historical provenance.
