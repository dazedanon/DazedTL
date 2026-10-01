# DazedTL

An Electron application migrating the existing DazedTL translation engine into a new interface.

## Current scope

RPG Maker MV/MZ has a Guided Workflow with preparation, context, selected-file translation,
application, layout review, and local patch packaging. **Translate files** opens the same
selection and run controls directly. Guided translation offers Batch (recommended) and Live API;
cost estimation is a separate action. Ace adds archive extraction, Sinflower RV2JSON conversion,
and native repacking around those same JSON phases. Its bundled executables require Windows
or Wine; executables and the Wine prefix are cached in the app profile. WOLF's guided workflow is deferred.

Len's method follows the maintained engine skills, with shared project context,
saved progress, inspectable requests, and Agent, Live API, and API Batch execution.
Any game folder can be opened for investigation. Its engine-specific extraction, fitting,
native reconstruction, and runtime QA remain the coding assistant's responsibility through the skills and tools.
Existing phased RPG Maker jobs retain their recovery path in Guided Workflow. Resume an
unfinished API run before starting another phase or estimate so its provider work stays attached.
Real provider billing and native game playtesting still need validation;
application distribution is pending. Guided image editing remains a separate assistant task.

## Development launch

Keep this checkout beside `DazedMTLTool`, which supplies engine source during migration.
Use the Node and Python versions in [.node-version](.node-version) and [.python-version](.python-version), and the npm version in [app/package.json](app/package.json).
Setup installs locked dependencies into this checkout's own `app/node_modules` and `.venv`.
Launching, building, and testing also accept newer Node releases within the pinned major version.

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
Project-format upgrades retain the original `projects.json` in workspace `backups/` before atomic replacement; the current registry format is version 3.
To restore a project backup, close the app, retain the current file, and copy the chosen backup to `projects.json` using an app version that supports that format.

See [architecture](docs/architecture.md) for code ownership, [AGENTS.md](AGENTS.md) for contribution rules, and the [migration record](docs/migration.md) for historical provenance.

## Translate a game

Open an MV/MZ or Ace game and choose **Guided workflow**. Preserve the original before
preparing game files, then review the runtime file list and game version for Git setup.
Import the database and a small map selection, prepare and save context, and translate
database names before dialogue. Batch pauses for cost approval before submission.
Advanced text uses the existing variable-cache and audited script/plugin phases.

Review accumulated outputs before applying them. Rewrap requires a completed scan with
the same files and settings. Use the scoped QA/playtest tasks as needed, then record your
review of the current scope, checkpoint it, and build a local patch ZIP. Review records
bind to exact file bytes; later changes require another review. This records the user's
review and playtest, not an automated claim that the game has passed QA.

To use **Len's method**, select a translation mode, set the image scope and project instructions,
then copy the starting prompt into a coding assistant with access to the game and engine checkout.
Keep DazedTL open: the prompt's project helper uses the running app to save state and control its jobs.
The same prompt resumes saved work. The app observes the assistant's saved reports; it does not host or keep that assistant running.

The helper preserves the selected source, establishes the original/translation Git branches,
records the game version, and prepares shared guidance before compiling translation requests.
API runs require review of their complete request set and cost estimate. Inspect the actual context,
source text and accepted outputs under Requests & results. Pausing a Batch run stops local polling;
Cancel provider batch requests remote cancellation and retains any completed results available from the provider.
An uncertain submission is never retried automatically. Reconcile its provider job or review an uncertain Live request before preparing another quote.

Request inspection shows each line's text type and known or unknown speaker. Unknown speakers are allowed;
specific source ambiguities appear as review notes beside the translation, with links from the run to affected requests.
Check those notes against the source before marking the request source-checked. A correction makes that review pending again.

Source & versions exposes backups, reviewed checkpoints, local patch packaging, and official-update preview/apply/recovery.
For a new official release, stage a separate copy and finish its engine-specific preparation before previewing the update.
Ordinary MV/MZ writes preserve existing Japanese in _original. Rebasing source metadata after an update requires the exact current original-branch bytes and commit.
Native formats use their engine's source/injection sidecars. Keep the selected game available throughout the work.

Working records and guidance stay in the game's ignored .dazedtl folder; Git tracks the runtime patch and matching originals.
Source and workspace snapshots share a deduplicated store in .dazedtl/backups/v2. Unchanged files are stored once; unchanged snapshots are reused.
The entire .dazedtl/backups directory is excluded from workspace snapshots, and .dazedtl stays out of Git and release packages.
Keep that backup directory together when moving the game. Existing full-copy backups in the app workspace remain readable and are never deleted automatically.
Guided **Prepare** shows the exact saved location and an **Open backup folder** action.
If a backup is deleted or becomes unreadable, its status changes to unavailable. Creating a
replacement saves the game's current files; it does not recover the deleted original.
A local patch does not publish a repository.
GameUpdate's public commit marker is included only when the existing updater checks can verify it against the configured tracked branch.

In **Source & versions**, use **List restore points** to select a source or translation-workspace backup.
Restore writes a verified copy into a new folder outside the game; existing folders are never overwritten.
Source snapshots restore game files. Workspace snapshots restore the contents of .dazedtl, including guidance,
accepted translations, custom tools and image work, but not the backup store itself.
Connections, app-owned runs and their provider state remain in the app profile.

If the app profile is unavailable, inspect and restore the portable store from this checkout:

```bash
python scripts/backups.py --game "/path/to/game" list
python scripts/backups.py --game "/path/to/game" verify --id SNAPSHOT_ID
python scripts/backups.py --game "/path/to/game" restore --id SNAPSHOT_ID --destination "/path/to/new-recovery-folder"
```

Add `--legacy-backups "/path/to/old/workspace/backups/PROJECT_ID"` before the command to include older full-copy backups.
Do not edit the store's objects or remove snapshot files manually; several restore points can share the same content.

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
