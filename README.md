# DazedTL

An Electron application migrating the existing DazedTL translation engine into a new interface.

## Current scope

The Translation workspace follows Len's maintained engine skills, with shared project context,
saved progress, inspectable requests, and Agent, Live API, and API Batch execution.
Any game folder can be opened for investigation. Its engine-specific extraction, fitting,
native reconstruction, and runtime QA remain the coding assistant's responsibility through the skills and tools.
Existing phased RPG Maker jobs remain available for recovery in the same workspace.
Real provider billing and native game playtesting still need validation; application distribution is pending.

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
Choose the connection's model under Preferences; Advanced model options starts at 50 entries per request, with a custom override for each connection and model, plus automatic or custom estimate rates.
Options are remembered separately for each connection and model; each new run retains its resolved size and rates for resume.
Automatic rates identify their catalog or built-in source; unknown prices require custom rates, with 0 supported for free models.
Existing app-local settings are retained in backups during migration; connections with an unknown provider need your review.

## Diagnostics and recovery

**Copy diagnostics** in the sidebar copies versions and recent error metadata, including when the backend cannot start.
Local diagnostic logs live under the profile's `diagnostics/` folder, capped at three 64 KiB files per process; credentials, request bodies, game text, and raw stderr are excluded.
Future project-format upgrades retain the original `projects.json` in workspace `backups/` before atomic replacement; the current registry format is version 2.
To restore a project backup, close the app, retain the current file, and copy the chosen backup to `projects.json` using an app version that supports that format.

See [architecture](docs/architecture.md) for code ownership, [AGENTS.md](AGENTS.md) for contribution rules, and the [migration record](docs/migration.md) for historical provenance.

## Translate a game

Open the game, select a translation mode, set the image scope and project instructions,
then copy the starting prompt into a coding assistant with access to the game and engine checkout.
Keep DazedTL open: the prompt's project helper uses the running app to save state and control its jobs.
The same prompt resumes saved work. The app observes the assistant's saved reports; it does not host or keep that assistant running.

The helper preserves the selected source, establishes the original/translation Git branches,
records the game version, and prepares shared guidance before compiling translation requests.
API runs require review of their complete request set and cost estimate. Inspect the actual context,
source text and accepted outputs under Requests & results. Pausing a Batch run stops local polling;
Cancel provider batch requests remote cancellation and retains any completed results available from the provider.
An uncertain submission is never retried automatically. Reconcile its provider job or review an uncertain Live request before preparing another quote.

Source & versions exposes backups, reviewed checkpoints, local patch packaging, and official-update preview/apply/recovery.
For a new official release, stage a separate copy and finish its engine-specific preparation before previewing the update.
Ordinary MV/MZ writes preserve existing Japanese in _original. Rebasing source metadata after an update requires the exact current original-branch bytes and commit.
Native formats use their engine's source/injection sidecars. Keep the selected game available throughout the work.

Working records and guidance stay in the game's ignored .dazedtl folder; Git tracks the runtime patch and matching originals.
Source and workspace backups are retained separately in the app workspace. A local patch does not publish a repository.
GameUpdate's public commit marker is included only when the existing updater checks can verify it against the configured tracked branch.

Engine adapter authors and assistant integrations should use the [translation contract](docs/translation-contract.md).

## Development checks

Run the full behavior suite from this checkout with `node scripts/test.mjs`
(or `npm test` from `app`). It uses the local Python environment and Node's
built-in test runner, with one enforced wall-clock budget including
startup, fixtures, and teardown. Tests use temporary workspaces and controlled
API responses; no provider, game folder, credentials, or sibling checkout is needed.

For focused iteration, use `.venv/bin/python -I -B -m unittest discover -s tests -t . -p test_projects.py`
or `node --test --test-isolation=none tests/application.test.ts` from the root.
Run `node scripts/build.mjs` separately for TypeScript checking and the renderer build.
