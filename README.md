# DazedTL

An Electron application migrating the existing DazedTL translation engine into a new interface.

## Current scope

Overview, provider settings, and the initial Guided RPG Maker MV/MZ path are connected to the existing Python backend.
The guided slice includes file preparation, context editing, database/dialogue phases, and run controls.
Remaining RPG Maker phases, WOLF, Ace, Len's Method, and other engines still use DazedMTLTool.
Live provider execution still needs validation; packaging and distribution are pending.

## Development launch

Keep this checkout beside `DazedMTLTool`, which supplies the existing Python environment and backend during migration.
Node and the dependencies in [app/package.json](app/package.json) are required; an ignored `app/node_modules` link can reuse the sibling's desktop dependencies.

```sh
node scripts/build.mjs
node scripts/start.mjs
```

`START.sh`, `START.command`, and `START.bat` use the same launcher.
Use `node scripts/start.mjs --offline` to inspect the UI with provider execution disabled.

The default profile is `DazedTLNext`, separate from the existing app.
Projects, credentials, and runs live in its workspace outside this checkout.

| Optional environment variable | Purpose |
| --- | --- |
| `DAZEDTL_LEGACY_ROOT` | Preserved DazedMTLTool checkout |
| `DAZEDTL_PYTHON` | Python executable with backend dependencies |
| `DAZEDTL_NEXT_PROFILE` | Electron profile location |
| `DAZEDTL_NEXT_WORKSPACE` | Project and run storage location |

See [architecture](docs/architecture.md) for code ownership, [AGENTS.md](AGENTS.md) for contribution rules, and the [migration record](docs/migration.md) for historical provenance.
