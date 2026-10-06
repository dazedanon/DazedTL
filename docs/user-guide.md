# Using DazedTL

This guide covers the app's workflows.
For setup and current limitations, see the [README](../README.md).

## Open a game

Choose **Open a game** on Overview and select the game folder.
The app prepares working copies of the selected files automatically, and reopening a project restores them with its saved translation progress.
RPG Maker MV/MZ and Ace games use the guided **Translation** workflow.
Any game folder can use [Len's method](#lens-method).

## Translation workflow

Translation follows seven stages: **Prepare → Context → Translate → Plugin text → Images → Apply & Fitting → Release**.
Each stage opens one focused task, and you can move between tasks without finishing them.
Alt+Left and Alt+Right (Option on macOS) move to the previous or next task, and Ctrl+S (Cmd+S) saves Guidance, Layout and Settings.
Navigation never starts paid work.

### Prepare

Preserve the original, prepare the game files, then save a version baseline with the game version.
The baseline sets up Git so later game updates can be compared and merged.

### Context

In **Investigation**, use **Copy investigation task** and paste it into your coding assistant.
The assistant identifies speaker formats, runs the local name scanner, then investigates the glossary, characters, voice and game context.
The scanner makes no API requests.
**Add game folder** includes an earlier game as a read-only terminology reference in the next copied task.
Re-copy the task after changing reference folders.
**View names** opens the saved scan, and **Detection settings** holds speaker rules and overrides.
Optional API name translation is available from the name-scan panel.
Edit the resulting files in **Guidance**.
Measured character limits are saved automatically during investigation; **Layout** shows them and allows manual changes.

### Translate

Translate has three tasks: **Database files**, **Maps & events** and **Event / plugin codes**.
All supported files start selected.
Translate database names first, then maps, CommonEvents and Troops; narrow the scope to test an early scene.
The file selector supports search, groups, map names, Ctrl/Cmd toggles and Shift ranges, and filtering keeps checked files.

Each **Translate** click prepares a fresh local estimate and opens the cost review.
Nothing is charged until you approve it, and declining discards the preparation.
If the estimate finds no new API requests, the result says so and no charge occurs.
Saved runs never block a new translation; the cost review warns about possible duplicate charges when earlier requests overlap.

Batch work pauses for cost approval before submission.
An approved, unchanged Batch queue continues after reopening the app or a dropped connection, skipping requests the provider already received.
Cancellation and newer overlapping approvals stop automatic continuation.
Files with active or unresolved Batch work are locked against source reloads.

**Event / plugin codes** investigates variables, plugin commands, scripts and labels before translation.
Enable only the investigation's confirmed codes, variable IDs, plugin handlers and script patterns, or skip the task if none are needed.
Translate audited assignments first, then review and update comparisons from their saved mappings.

**Options** holds task settings, opens the translated folder, and reloads checked files from the current game.
Reloading archives previous working copies and their cached results.

### Run history and inspection

**Run history** on Translate lists approved runs, including failed and canceled ones; **History** also includes other project activity.
**Inspect**, or a file's inspect icon, opens the request inspector.
**Source** shows prepared text and matched context, **Response** shows the reply or error, and **Technical** shows token usage, the exact API payload and the run log.
**File contents** shows the file's current text even when no request was prepared.
The inspector also holds Batch controls: provider cancellation, queue continuation, collection recovery and reviewed reapplication of saved output.
Finished responses, including partial results from canceled Batches, stay available for collection.

Files with validation problems show a warning.
Open Inspect and choose **Review issues** to read rejected requests and their responses.
Valid translations are kept, and rejected lines keep their original text until the next Translate.
Older duplicate menu-choice responses appear under **Unused** when the app can show which response supplied the saved text.

### Images

Images opens the shared Image Manager.
The assistant finds images that contain text before copies are made editable; **Choose images myself** skips discovery.
Copying a task only uses the clipboard; it does not start an assistant or provider work.
The manager supports MV/MZ encrypted images and loose PNG files, with batch review, guarded application and restore of preserved originals.
The optional text editor keeps boxes, source text and translations, supports installed local OCR, and uses the same estimate and approval as other API work.

### Apply & Fitting

Apply overwrites the checked game files that have saved output; it never merges or synchronizes automatically.
You can apply saved partial translations while Batch work continues.
Untranslated text stays as saved, and later results need another Apply.
Rewrap needs a completed scan with the same files and settings.
Optional QA and game tools stay here, and **Tools** installs or updates TL Inspector and Forge for MV/MZ.
Apply and playtest an early scene before expanding the scope.

### Release

**Release** builds a clean game ZIP or a local patch ZIP.
A patch build saves a local checkpoint and workspace backup first; a clean game ZIP leaves the working game untouched.
Destinations must be outside the game, the app workspace and the engine, and replacing an existing archive needs approval.
The app checks the package contents and finished archive before offering its folder; these checks do not mean the game passed QA.
GameUpdate metadata keeps the engine's clean-commit and upstream checks, and the app never publishes or pushes.

### RPG Maker Ace

Ace adds archive extraction, Sinflower RV2JSON conversion and native repacking around the same stages.
Release verifies saved packing evidence against the current JSON and native files.

## Len's method

Len's method runs translation through a coding assistant using the bundled engine skills, with Agent, Live API and API Batch execution.
Select a translation mode, set the image scope and project instructions, then copy the starting prompt into a coding assistant with access to the game and engine checkout.
Keep DazedTL open: the prompt's project helper uses the running app to save state and control jobs.
The same prompt resumes saved work.
DazedTL shows the assistant's saved reports; it does not host or keep the assistant running.

The helper preserves the selected source, sets up the original and translation Git branches, records the game version and prepares shared guidance before compiling requests.
For engines other than RPG Maker, extraction, fitting, native reconstruction and runtime QA remain the assistant's work through the bundled skills and tools.
Existing phased RPG Maker jobs keep their recovery path in Translation.
Resume an unfinished API run before starting another phase or estimate so its provider work stays attached.

API runs require reviewing the complete request set and cost estimate.
Inspect context, source text and accepted outputs under **Requests & results**.
Each line shows its text type and known or unknown speaker; source ambiguities appear as review notes beside the translation.
Check those notes against the source before marking the request source-checked; a correction makes that review pending again.
Pausing a Batch run stops local polling, and **Cancel provider batch** requests cancellation while keeping completed results.
An uncertain submission is never retried automatically; reconcile its provider job or review the uncertain Live request before preparing another quote.
Len's manual checkpoint and patch controls are under **Advanced setup & patch tools**.

## Game updates

For a new official release, **Project tools → Game updates** stages a separate copy for comparison.
Finish any engine-specific preparation of that copy, preview the changes, then apply the update.
Each step appears under **History → Other activity**, where **Inspect** shows its saved result and log.
Ordinary MV/MZ writes keep the existing Japanese in `_original`.
Rebasing source metadata after an update requires the exact current original-branch bytes and commit.
Native formats use their engine's source and injection sidecars.
Keep the selected game available throughout the work.

## Backups and recovery

Working records and guidance stay in the game's `.dazedtl` folder, which is kept out of Git and release packages.
Git tracks the runtime patch and matching originals.
Backups live in `.dazedtl/backups/v2`, where unchanged files are stored once.
Keep that folder with the game when moving it.
Older full-copy backups in the app workspace remain readable and are never deleted automatically.

**Project tools → Backups & recovery** saves game and project backups and opens their folders.
**Recover files…** restores a chosen copy into a new folder outside the game; existing folders are never overwritten.
Game backups restore game files.
Project backups restore the contents of `.dazedtl`, such as guidance, accepted translations, custom tools and image work, but not the backup store itself.
Connections, app-owned runs and their provider state stay in the app profile.
A deleted or unreadable backup shows as unavailable; saving a new one captures the current files and does not recover the original.
After a successful game backup, references to deleted project backups and engine investigations are archived automatically.

If the app profile is unavailable, inspect and restore the store from a DazedTL checkout:

```bash
python scripts/backups.py --game "/path/to/game" list
python scripts/backups.py --game "/path/to/game" verify --id SNAPSHOT_ID
python scripts/backups.py --game "/path/to/game" restore --id SNAPSHOT_ID --destination "/path/to/new-recovery-folder"
```

Add `--legacy-backups "/path/to/old/workspace/backups/PROJECT_ID"` before the command to include older full-copy backups.
Do not edit the store's objects or remove snapshot files manually; several restore points can share the same content.

## API setup

In Settings, choose a provider, paste its API key and save the connection.
**Check connection** requests the provider's model list without generating text.
Choose the connection's model under Preferences.

**Advanced model options** sets per-connection and per-model request options, and new runs keep the values they started with:

- Requests start at 50 entries each, with a custom override.
- **Output token allowance** defaults to 32,768 tokens per request, lowered to a known model or host limit.
  It covers reasoning and visible output where the provider shares that budget, and it is a maximum, not a target.
- For OpenAI, **Batch token allowance** caps estimated input tokens across active Guided Batches on the same connection and model.
  Override its conservative default with the model's Batch queue limit from [OpenAI Limits](https://platform.openai.com/settings/organization/limits), and leave headroom for other jobs on the account.
- Estimate rates are automatic when the catalog or built-in table knows the model.
  Unknown prices need custom rates, and 0 is allowed for free models.

Custom Batch rates can be set when needed; they do not make an unsupported model or host eligible.
Saved runs keep their original options; prepare a fresh estimate to use new values.
Settings carried over from the older app are backed up, and connections with an unknown provider need your review.

### OpenRouter

Save an OpenRouter API key, check the connection, then choose or enter the full model ID (such as `anthropic/claude-sonnet-4.5`) in Preferences.
Live prices load when you open model options or prepare an estimate, including the selected host's rates.
**Check connection** caches your account's model catalog, and saving a different model or host checks its Batch endpoints and prices automatically.
**Check again** refreshes the catalog or retries a failed check.

To choose a hosting provider, select the model in Preferences, then edit the connection and choose **Host**.
**Refresh hosts** reloads the list.
**Automatic** lets OpenRouter choose among compatible endpoints; a selected host is exclusive, so an unavailable host returns an error instead of falling back.
The host list is public and does not override your account's privacy or routing restrictions.

New runs request strict [Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs), and incompatible endpoints fail instead of switching to plain JSON.
OpenRouter's [Batch API](https://openrouter.ai/docs/batch-quickstart) uses a 24-hour window and cannot cancel submitted work.
**Stop queued work** prevents further submissions while submitted work continues, and **Continue queued work** resumes the unchanged approved queue.
Results missing from a finished or expired provider record stay blocked for inspection or **Retry collection**; they are never resubmitted automatically.
Downloaded responses stay available locally after the provider's retention expires.
**Technical** shows collected OpenRouter charges separately from any separately billed BYOK inference estimate.

## Diagnostics

**Copy diagnostics** in the sidebar copies versions and recent error details, even when the backend cannot start.
Diagnostic logs live in the profile's `diagnostics/` folder, capped at three 64 KiB files per process.
They exclude credentials, request bodies, game text and raw error output.

If a view fails, its recovery panel offers **Try again**, **Copy diagnostics** and **Reload interface** while navigation stays available.
Retry and reload save pending recovery drafts first; a failed save keeps the action blocked and retryable.
If the interface freezes or exits, a dialog offers to wait, copy diagnostics or reload.
Reloading keeps the backend and running jobs, and recovery never resubmits the failed action.

Project-format upgrades keep the original `projects.json` in the workspace `backups/` folder.
To restore one, close the app, keep the current file, and copy the chosen backup to `projects.json` using an app version that supports that format.
