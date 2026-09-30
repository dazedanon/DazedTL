# DazedTL

An Electron application migrating the existing DazedTL translation engine into a new interface.

## Current scope

Overview, provider settings, and the initial Guided RPG Maker MV/MZ path are connected to the existing Python backend.
The guided slice includes file preparation, context editing, database/dialogue phases, and run controls.
Remaining RPG Maker phases, WOLF, Ace, Len's Method, and other engines still use DazedMTLTool.
Live provider execution still needs validation; packaging and distribution are pending.

## Development launch

Keep this checkout beside `DazedMTLTool`, which supplies engine source during migration.
Use the Node and Python versions in [.node-version](.node-version) and [.python-version](.python-version), and the npm version in [app/package.json](app/package.json).
Setup installs locked dependencies into this checkout's own `app/node_modules` and `.venv`.

```sh
node scripts/setup.mjs
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

## API setup

In Settings, choose a provider, paste its API key, and save the connection.
**Check connection** requests the provider's model list without generating text; saving alone never contacts the provider.
Choose the connection's model under Preferences; request sizes, estimate rates, and formatting are under Advanced.
Existing app-local settings are retained in backups during migration; connections with an unknown provider need your review.

## Diagnostics and recovery

**Copy diagnostics** in the sidebar copies versions and recent error metadata, including when the backend cannot start.
Local diagnostic logs live under the profile's `diagnostics/` folder, capped at three 64 KiB files per process; credentials, request bodies, game text, and raw stderr are excluded.
Future project-format upgrades retain the original `projects.json` in workspace `backups/` before atomic replacement; the current format remains version 1.
To restore a project backup, close the app, retain the current file, and copy the chosen backup to `projects.json` using an app version that supports that format.

See [architecture](docs/architecture.md) for code ownership, [AGENTS.md](AGENTS.md) for contribution rules, and the [migration record](docs/migration.md) for historical provenance.
