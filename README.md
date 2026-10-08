# DazedTL

DazedTL is a desktop app for translating games with its bundled translation engine.
RPG Maker MV/MZ and Ace games use a guided five-stage workflow, and Assistant-led, built on Len's game-translation skills, lets a coding assistant translate any game through the running app.
The [user guide](docs/user-guide.md) covers both workflows.

## Current limitations

- WOLF's guided workflow is deferred; other engines are supported only through Assistant-led.
- Real provider billing and native game playtesting still need validation.
- Application distribution is pending, so DazedTL runs from a checkout.

## Setup

This checkout includes its engine code, worker helpers, tokenizers, native tools and translation toolkit.
No DazedMTLTool installation or sibling engine checkout is required.
See [resource ownership](docs/architecture.md#ownership) for the engine and shared prompt locations, saved-run compatibility and override behavior.
Use the Node and Python versions in [.node-version](.node-version) and [.python-version](.python-version), and the npm version in [app/package.json](app/package.json).
Setup installs locked dependencies, including the formatting tools, into this checkout's own `app/node_modules` and `.venv`.
Launching, building, and testing also accept newer Node releases within the pinned major version.

```sh
node scripts/setup.mjs
node scripts/build.mjs
node scripts/start.mjs
```

`START.sh`, `START.command`, and `START.bat` use the same launcher.
Use `node scripts/start.mjs --offline` to inspect the UI with provider execution disabled.

The default profile is the `DazedTL2` folder in the system's application data folder, separate from DazedMTLTool; an existing pre-release `DazedTLNext` profile keeps being used.
Projects, credentials, and runs live in its workspace outside this checkout.

| Optional environment variable | Purpose |
| --- | --- |
| `DAZEDTL_PYTHON` | Python executable with backend dependencies |
| `DAZEDTL_PROFILE` | Electron profile location |
| `DAZEDTL_WORKSPACE` | Project and run storage location |

## Development checks

Run the full behavior suite from this checkout with `node scripts/test.mjs` (or `npm test` from `app`).
It uses the local Python environment and Node's built-in test runner, with one enforced wall-clock budget including startup, fixtures, and teardown.
The runner reports the five slowest Python tests to make runtime regressions visible.
Tests use temporary workspaces and controlled API responses; no provider, game folder, credentials, or sibling checkout is needed.

For focused iteration, use `.venv/bin/python -I -B -m unittest discover -s tests -t . -p test_projects.py` or `node --test --test-isolation=none tests/application.test.ts` from the root.
Run `node scripts/build.mjs` separately for static checks and the renderer build.
It checks formatting, that stylesheets use the [design tokens](docs/architecture.md#visual-design) and that the [generated API contracts](docs/architecture.md#api-changes) are current, lints with type-aware [Oxlint](.oxlintrc.json) (including the React hooks rules) and [Ruff](ruff.toml), and type-checks the renderer, the Electron main process and DazedTL-owned Python with [Pyright](pyrightconfig.json).
Launching builds a missing renderer without these checks.
Format with `node scripts/format.mjs`; it applies Prettier and Ruff defaults and leaves the bundled engine, Markdown and JSON unchanged.
To skip the one-time formatting commit in local `git blame`, run `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

## Documentation

- The [user guide](docs/user-guide.md) explains the app's workflows, API setup, backups and diagnostics.
- [Architecture](docs/architecture.md) covers code ownership, boundaries and design decisions.
- The [translation contract](docs/translation-contract.md) is for engine adapter authors and assistant integrations.
- [AGENTS.md](AGENTS.md) holds contribution rules.
- The [migration record](docs/migration.md) keeps historical provenance.
