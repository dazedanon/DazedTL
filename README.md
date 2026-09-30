# DazedTL

A clean Electron application built around the existing DazedTL translation engine.
The migration is incremental, with Guided Workflow and Len's Method as the two primary translation methods.

## Current migration slice

- A compact Overview with the active game, status, next action, and recent projects.
- Project identity, translation method, and visible screen stored separately.
- Guided RPG Maker MV/MZ file preparation, game-context editing, database and dialogue phases, live/batch controls, approvals, saved-run recovery, and output handling.
- Provider settings and credentials scoped to this application's own workspace.

The guided path calls the existing Python implementations through one temporary compatibility adapter.
The engine parser, context assembly, phase profiles, and translation runner have not been reimplemented.
WOLF, Ace, Len's Method, and the less-used manual engines remain in the current application while their flows are migrated.

## Development launch

Keep this folder beside the preserved `DazedMTLTool` repository during this migration slice.
The current repository supplies the Python environment and the temporary backend implementation.

```sh
node scripts/build.mjs
node scripts/start.mjs
```

`START.sh`, `START.command`, and `START.bat` call the same development launcher.
The launcher expects Node to be available.
It can reuse the existing Electron/React development dependencies using an ignored `app/node_modules` link.
A normal dependency installation in `app/` can replace that development link later.
There is no installation or update migration applied to the existing app.

Optional environment settings:

- `DAZEDTL_LEGACY_ROOT`: location of the preserved DazedMTLTool checkout.
- `DAZEDTL_PYTHON`: Python executable with the current backend dependencies.
- `DAZEDTL_NEXT_PROFILE`: separate Electron profile location.
- `DAZEDTL_NEXT_WORKSPACE`: separate writable project and run storage.

The default profile is named `DazedTLNext`, separate from the existing `DazedTL` profile.
Use `node scripts/start.mjs --offline` to disable provider execution while inspecting the interface.
Opening the application does not start a translation or submit provider work.

## Source layout

```text
app/        Electron shell and React pages
backend/    Project model, application API, and workflow coordination
resources/  Shipped application assets
scripts/    Build and development launch commands
docs/       Architecture and migration decisions
```

User projects, API credentials, logs, and translation workspaces live outside the source tree.
Generated renderer files and development dependencies are ignored.

See [architecture](docs/architecture.md) and [migration](docs/migration.md) for the intended boundaries and remaining work.
