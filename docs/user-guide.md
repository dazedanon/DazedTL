# Using DazedTL

This guide covers the app's workflows.
For setup and current limitations, see the [README](../README.md).

## Open a game

Choose **Open a game** on the Project page and select the game folder.
A new game asks how to translate it: **Guided steps** for RPG Maker MV/MZ and Ace games, or [Assistant-led](#assistant-led) for any game.
**Translation** in the sidebar then opens that method.
**Change method** on the Project page switches later; the other method's saved work stays and returns if you switch back.
The Project page's **Status** shows the next unfinished task and every stage's tasks.
**Continue** (**Start** for a new game) opens that next task, and **Last opened** beside it returns to the task you left; once every required task is done, **Resume** returns there instead.
Optional tasks say **Optional** until they are done, and they never hold up the next step: Plugin files counts as done once its applied work has nothing left waiting, and Release while its last ZIP is up to date.
Its **History**, **Game updates** and **Backups** tabs serve both methods.
The app prepares working copies of the selected files automatically, and reopening a project restores them with its saved translation progress.

A project belongs to the game folder's location, so a moved or copied game, a new profile or a reinstall opens the folder as a new project.
Plugin files and Images then show the work another project saved there and change nothing until you choose; until then the Project page and their tabs mark them **Needs review**.
**Use saved progress** keeps findings, choices, working and edited copies, reviews and applied files.
Tasks copied in the other project are not accepted, so copy the task again to continue; plugin translations that are not applied yet are checked again by that task.
Applied images stay restorable, and so do applied plugin files whose saved backups still match; an Apply or Restore that was interrupted can only be finished in the project it belongs to.
**Start over** moves the saved work to `.dazedtl/archived` under a dated name and starts fresh.
Applied files stay in the game but can no longer be restored from the task, and applied images leave patch ZIPs.
Set up likewise reuses the backup of the original the game folder already holds instead of saving its current files, which may already contain translations; **Back up current files instead** saves them as the original after a review.

## Translation workflow

Translation follows five stages: **Set up → Context → Translate → Check → Release**.
Each stage opens one focused task, and you can move between tasks without finishing them.
Optional tasks say so on their tab.
Existing projects reopen on the task that now holds their work.
Alt+Left and Alt+Right (Option on macOS) move to the previous or next task, and Ctrl+S (Cmd+S) saves Guidance, Line widths and Settings.
Navigation never starts paid work.
Every list uses the same words for where work stands: **Not started**, **Working**, **Waiting** (with your assistant), **Needs review**, **Ready to apply**, **Applied**, **Done** (finished work that does not change the game), **Outdated** (what it was based on changed), **Blocked** and **Skipped**.
The detail beside each says why.

### Assistant tasks

Tasks you copy to a coding assistant, such as Names & glossary, Line widths, Other event text, Plugin files, Images, Text QA and the player walkthrough, are listed under **Assistant tasks** on the Project page, and the count in the top bar opens that list.
Each shows **Waiting** with when it was copied until a result comes back, **Needs review** when results need your decision, **Outdated** when what the task was based on changed, or **Blocked** with the reason.
Finished tasks leave the list; their results stay in their own task.
**Dismiss** clears a task you abandoned, so its task reads **Not started** again; saved results are kept, and copying the task again brings it back.
When you return to the DazedTL window, image results your assistant saved are imported and checked as **Refresh results** would; other tasks show their saved results as soon as they appear.

### Set up

**Set up this game** asks for the game version and whether the game already contains translations.
Its one button backs up the original, prepares the game files (data, `plugins.js` and GameUpdate files) and saves the version, showing each step's progress.
The saved version sets up Git so later game updates can be compared and merged.
If a step fails or you stop it, the reason appears beside the button, and **Finish setup** continues from that step.
Replacing a missing backup still asks for your approval first.
**Preparation tools** reruns a single preparation step.

### Context

In **Names & glossary**, use **Copy names & glossary task** and paste it into your coding assistant.
The assistant identifies speaker formats, runs the local name scanner, then investigates the glossary, characters, voice and game context.
The scanner makes no API requests.
**Add game folder** includes an earlier game as a read-only terminology reference in the next copied task.
Re-copy the task after changing reference folders.
**View names** opens the saved scan, and **Speaker detection** holds speaker rules and overrides.
Optional **Translate names with API…** in the name scan opens the paid review directly, using the project's Batch or Live choice.
Edit the resulting files in **Guidance**.
Measured line widths are saved automatically when the assistant reports them; **Line widths** shows them and allows manual changes.

### Translate

Translate has four tasks, **Database files**, **Maps & events**, **Other event text** and **Images**, and the optional **Plugin files** task.
All supported files start selected.
Translate database names first, then maps, CommonEvents and Troops; narrow the scope to test an early scene.
The file selector supports search, groups, map names, Ctrl/Cmd toggles and Shift ranges, and filtering keeps checked files.

The file list's **Lines** shows the lines saved of the lines the latest run prepared; while a Live run works it shows the lines saved so far.
The Project page totals lines translated, files applied and the recorded cost.
Each **Translate** click prepares a fresh local estimate and opens the cost review.
Nothing is charged until you approve it, and declining discards the preparation.
If the estimate finds no new API requests, the result says so and no charge occurs.
Saved runs never block a new translation; the cost review warns about possible duplicate charges when earlier requests overlap.

Batch work pauses for cost approval before submission.
An approved, unchanged Batch queue continues after reopening the app or a dropped connection, skipping requests the provider already received.
Cancellation and newer overlapping approvals stop automatic continuation.
Files with active or unresolved Batch work are locked against source reloads.

**Other event text** investigates variables, plugin commands, scripts and labels before translation.
Enable only the investigation's confirmed codes, variable IDs, plugin handlers and script patterns.
When the findings leave nothing to enable, **Confirm nothing to translate** in **Source choices** finishes the task.
Translate audited assignments first, then review and update comparisons from their saved mappings.

**Options** holds task settings and opens the translated folder.
**Reload from game…** beside the file list replaces the checked working files with the current game files.
Reloading archives previous working copies and their cached results.

### Run history and inspection

The Project page's **History** lists approved runs, including failed and canceled ones, estimates and other project activity.
**Run history** on a Translate task shows that stage's runs over the task; close it to return to your files.
**Inspect**, or a file's inspect icon, opens the request inspector.
**Source** shows prepared text and matched context, **Response** shows the reply or error, and **Technical** shows token usage, the exact API payload and the run log.
**File contents** shows the file's current text even when no request was prepared.
A complete Live or Batch run can reapply its saved output to the game through the usual Apply review; Live runs offer **Reapply output** in the inspector header.
The inspector also holds Batch controls: provider cancellation, queue continuation and collection recovery.
Re-applying output or resuming a run from History opens its review in Translation.
Finished responses, including partial results from canceled Batches, stay available for collection.

Files with validation problems show a warning.
Open Inspect and choose **Review issues** to go to the request that needs attention: an unconfirmed submission first, then a rejected one with the provider's reply.
Valid translations are kept, and rejected lines keep their original text until the next Translate.
Older duplicate menu-choice responses appear under **Unused** when the app can show which response supplied the saved text.

### Images

The Images task in Translate is the Image Manager, the same one Assistant-led shows in its **Images** tab.
The assistant finds images that contain text before copies are made editable; **Choose images myself** skips discovery.
The footer walks the selected images through **Make editable**, **Copy image task**, **Refresh results** once a task is copied, and **Review & apply**; **More** holds the text editor, refreshes and recovery.
Copying a task only uses the clipboard; it does not start an assistant or provider work.
An edited copy saved in another image editor is checked again when you return to DazedTL.
The manager supports MV/MZ encrypted images and loose PNG files, with batch review, guarded application and restore of preserved originals.
The optional text editor keeps boxes, source text and translations, supports installed local OCR, and uses the same estimate and approval as other API work.
Images is done once applied images have nothing left waiting, or once a complete discovery leaves no recommended or uncertain image; **Exclude selected** records images you leave untranslated.

### Check

Check has three tasks: **Pending changes**, **Line width check** and the optional **Text QA**.
**Pending changes** lists everything reviewed and waiting to go into the game: translated text files, plugin files, images, line rewraps and QA fixes.
**Review & apply** opens one review of every part, and **Apply all** applies them in order, with each part's result beside it; **Leave out** keeps a part for later.
A part that did not apply leaves the game unchanged, and **Review again** prepares a new review of the parts left.
Line rewraps wait while translated text is applied with them, and QA fixes wait while text, rewraps or plugin files are applied with them, because each was checked against the game files those parts change; check line widths or prepare QA again afterwards.
The Review & apply buttons in Images, Plugin files, Line width check and Text QA open the same review for their own part.
Applying text overwrites the checked game files that have saved output; it never merges or synchronizes automatically.
You can apply saved partial translations while Batch work continues.
Untranslated text stays as saved, and later results need another Apply.
**Line width check** finds applied lines wider than the saved line widths and rewraps them; applying the rewraps needs a completed check with the same files and settings.
Translated plugin command text (357) loses its line breaks, so the check offers **Include 357** when that source is enabled but outside its event codes.
**Playtest tools** in the task header installs or updates TL Inspector and Forge for MV/MZ and holds their settings.
Apply and playtest an early scene before expanding the scope.

### Release

**Release** builds a clean game ZIP or a local patch ZIP.
**Player walkthrough** copies an optional task for your assistant to write a walkthrough for players.
A patch build saves a translation version and a project backup first; a clean game ZIP leaves the working game untouched.
Destinations must be outside the game, the app workspace and the engine; the fields say so as you type, and replacing an existing archive needs approval.
With no translation applied yet, the footer notes that the ZIP keeps the original text.
The last saved ZIP shows **Done** while it matches the game and **Outdated** once the game's runtime files change or another image is applied; build again to include later changes.
A ZIP saved by an earlier DazedTL version is not compared until you build it again.
The app checks the package contents and finished archive before offering its folder; these checks do not mean the game passed QA.
GameUpdate metadata keeps the engine's clean-commit and upstream checks, and the app never publishes or pushes.

### RPG Maker Ace

Ace adds archive extraction, JSON conversion and native repacking around the same stages, built in on every platform.
Set up's **Convert Ace data** step extracts an encrypted `Game.rgss3a` and converts `Data` to `ace_json` in Sinflower's RV2JSON format, with the equipment type names added for translation.
**Review native Ace packing** in Release writes the translated JSON back into `Data`; the original stays in Set up's backup.
Release verifies saved packing evidence against the current JSON and native files.

An encrypted game reads only its archive while one sits beside `Game.exe`, so Set up moves `Game.rgss3a` into `.dazedtl/ace` once its files are extracted.
The game in its folder then plays the translated files, and the clean game ZIP ships them unencrypted.
A patch ZIP for an encrypted game carries `Game.rgss3a` rebuilt with the translated files, so players replace one archive.
GameUpdate delivers loose files, which an encrypted game ignores, so share a new patch for each update instead.

## Assistant-led

Assistant-led runs translation through a coding assistant using Len's game-translation skills bundled with the engine, with Agent, Live API and API Batch execution.
Select a translation mode, set the image scope and project instructions, then copy the starting prompt into a coding assistant with access to the game and engine checkout.
Keep DazedTL open: the prompt's project helper uses the running app to save state and control jobs.
The same prompt resumes saved work.
DazedTL shows the assistant's saved reports; it does not host or keep the assistant running.

The helper preserves the selected source, sets up the original and translation Git branches, records the game version and prepares shared guidance before compiling requests.
For engines other than RPG Maker, extraction, line fitting, native reconstruction and runtime QA remain the assistant's work through the bundled skills and tools.
Guided steps work on the same game keeps its recovery path when you switch the method back.
Resume an unfinished API run before starting another phase or estimate so its provider work stays attached.

API runs require reviewing the complete request set and cost estimate.
Inspect context, source text and accepted outputs in the Project page's **History**.
Each line shows its text type and known or unknown speaker; source ambiguities appear as review notes beside the translation.
Check those notes against the source before marking the request source-checked; a correction makes that review pending again.
Pausing a Batch run stops local polling, and **Cancel provider batch** requests cancellation while keeping completed results.
An uncertain submission is never retried automatically; reconcile its provider job or review the uncertain Live request before preparing another quote.
Manual version and patch controls are under **Advanced setup & patch tools**.

## Game updates

For a new official release, the Project page's **Game updates** stages a separate copy for comparison.
Finish any engine-specific preparation of that copy, preview the changes, then apply the update.
**Discard release** drops a staged release you decide against; its preserved copy stays in **Backups**.
Each step appears under **History → Other activity**, where **Inspect** shows its saved result and log.
**Backups & recovery** on that tab opens the **Backups** tab.
Ordinary MV/MZ writes keep the existing Japanese in `_original`.
Rebasing source metadata after an update requires the exact current original-branch bytes and commit.
Native formats use their engine's source and injection sidecars.
Keep the selected game available throughout the work.

## Backups and recovery

DazedTL keeps two kinds of history: **Backups** are copies of the game or project files you can restore, and **Versions** are the Git history of the original game and the translation, used to merge game updates.
Working records and guidance stay in the game's `.dazedtl` folder, which is kept out of Git and release packages.
Git tracks the runtime patch and matching originals.
Backups live in `.dazedtl/backups/v2`, where unchanged files are stored once.
Keep that folder with the game when moving it.
Older full-copy backups in the app workspace remain readable and are never deleted automatically.

The Project page's **Backups** saves game and project backups and opens their folders.
The original backed up during setup stays the original; the **Game files** row shows the latest game backup.
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
Do not edit the store's objects or remove snapshot files manually; several backups can share the same content.

## API setup

In Settings, choose a provider, paste its API key and save the connection.
**Check connection** requests the provider's model list without generating text.
Choose the connection's model from **Model** on its Settings panel, on Translate or in Assistant-led; the menu lists the models the last check found and also accepts a typed model ID.
**Translation defaults** holds the target language and the advanced model options.
**Remove…** deletes the connection and its saved key, and another saved connection becomes active.
Unfinished runs that used it can no longer resume or collect their Batches, so the confirmation counts them and asks you to remove it anyway.

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

Save an OpenRouter API key, check the connection, then choose or enter the full model ID (such as `anthropic/claude-sonnet-4.5`) from **Model** on the connection panel.
Live prices load when you open model options or prepare an estimate, including the selected host's rates.
**Check connection** caches your account's model catalog, and saving a different model or host checks its Batch endpoints and prices automatically.
**Check again** refreshes the catalog or retries a failed check.

To choose a hosting provider, choose the model first, then edit the connection and choose **Host**.
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
