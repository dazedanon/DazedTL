# Using DazedTL

This guide explains how to translate a game with DazedTL.
To install it, see the [README](../README.md).

## The basics

- **Projects.** Every game folder you open is a project.
  Open one with **Open a game** on the Project page.
- **Two methods.** A new game asks how to translate it: **Guided steps** for RPG Maker MV, MZ and VX Ace, or [Assistant-led](#assistant-led) for any game.
  **Change method** on the Project page switches later and keeps the other method's work.
- **Your assistant.** Many steps copy a task for your AI coding assistant, such as Claude Code or Codex.
  Paste it into the assistant and keep DazedTL open; the results show up in DazedTL by themselves.
  Copying a task only uses the clipboard and never starts paid work.
- **Costs.** Anything that uses your API key shows a cost estimate first, and nothing is charged until you approve it.

## The Project page

**Status** shows what comes next.
**Continue** (**Start** for a new game) opens the next unfinished task, and **Last opened** returns to the one you left.
Optional tasks say so and never hold up the next step.

**Assistant tasks** lists the tasks you copied to your assistant and where each one stands; the count in the top bar opens it.
**Dismiss** clears a task you gave up on, and copying it again brings it back.

The other tabs are **History** (runs, estimates and other activity), **Game updates** and **Backups**.

Lists everywhere use the same words:

| Word | Meaning |
| --- | --- |
| **Waiting** | The task is with your assistant. |
| **Needs review** | Results need your decision. |
| **Ready to apply** | Results are ready to go into the game. |
| **Applied** | The results are in the game. |
| **Done** | Finished work that doesn't change the game. |
| **Outdated** | Something it was based on changed; redo it. |
| **Blocked** | It can't continue; the detail beside it says why. |

A project belongs to its folder, so a moved or copied game opens as a new project.
Plugin files and Images then offer **Use saved progress** to keep the earlier work, or **Start over**.

## Guided steps

Translation follows five stages: **Set up → Context → Translate → Check → Release**.
You can move between tasks at any time; Alt+Left and Alt+Right (Option on macOS) step through them, and Ctrl+S (Cmd+S) saves Guidance, Line widths and Settings.

### 1. Set up

**Set up this game** asks for the game's version and whether it already contains translations.
It then backs up the original, prepares the game files and starts version tracking, so later game updates can be merged.
If a step fails, the reason appears beside the button and **Finish setup** carries on.
**Preparation tools** reruns a single step.

### 2. Context

**Names & glossary**: copy the task to your assistant.
It finds the speakers, lists the names with a free local scanner, and writes the glossary, character notes and game context.
Edit what it wrote in **Guidance**.
**Add game folder** lets an earlier game in a series supply terms; copy the task again afterwards.

**Line widths** fills in from your assistant's measurements, and you can change them.

### 3. Translate

Translate has five tasks.

**Database files** and **Maps & events** translate with your API key:

1. Pick the files; all of them start selected.
   Translate the database first, and try a small early scene before the rest.
2. Choose **Batch** (often half the price, but can take hours) or **Live** (results arrive as you watch), and the model.
3. Click **Translate**, check the estimate and approve it.
4. Click **Apply** to write the translations into the game.

Approved Batch work carries on after DazedTL restarts.
**Reload from game…** starts selected files over from the game's current text.

**Other event text**: copy the investigation to your assistant.
It finds which variables, plugin commands and scripts hold text players see and turns those on.
Change any choice under **Source choices**, then translate like the other files.

**Plugin files**: copy the task to your assistant, which finds and translates the player-visible text in every plugin.
**Review & apply** shows what goes into the game.
Copy the task again to continue, or to have it recheck after you spot untranslated plugin text.

**Images** has four steps, and the filled button is always the next one:

1. **Investigate**: copy the task; your assistant recommends the images with text players read.
2. **Choose**: recommended images arrive ticked; untick any, or tick others under **Unsure** or **All images**.
3. **Translate**: copy the translation task; your assistant edits copies of the ticked images.
4. **Apply**: check the results, ask your assistant to redo any, then click **Apply to game**.

Clicking an image only previews it; its tick box, Space or Ctrl-click ticks it, and **Compare** shows the original beside the edited copy.

**When something fails.** A banner above the files explains a failed run, and **Run history** lists the task's runs.
**Inspect** shows each request's text, the AI's reply and the technical details.
Files with problems show a warning; **Review issues** jumps to them.
Lines the AI got wrong keep their original text until you translate again.

### 4. Check

Both Check tasks are optional:

- **Line width check** finds applied lines wider than the saved line widths and rewraps them; **Edit settings** chooses what it covers.
- **Text QA**: copy the task, and your assistant reviews the translated text.

**Playtest tools** at the top installs TL Inspector and Forge to help you playtest MV and MZ games.
Apply and playtest an early scene before translating everything.

Applying replaces the game's files with the translations.
If you edit a file in the game afterwards, applying it again replaces your edits, and the review names those files.
If applying stops midway, **Review restore** puts the files back.

### 5. Release

**Release** builds a clean game ZIP or a patch ZIP with only the changed files.
Save it outside the game folder.
Translations that aren't in the game yet need **Apply** first.
The ZIP shows **Outdated** once the game changes; build it again to include the changes.
**Player walkthrough** copies an optional task for your assistant to write a walkthrough for players.

### RPG Maker VX Ace

Set up's **Convert Ace data** unpacks an encrypted `Game.rgss3a` and converts the game data so it can be translated.
**Review native Ace packing**, in Check or Release, writes the translations back.
A patch ZIP for an encrypted game carries a rebuilt `Game.rgss3a`, so players replace one file.
GameUpdate can't update an encrypted game, so share a new patch for each update instead.

## Assistant-led

1. Choose a mode: **Agent Translation** (your assistant translates by itself), **Live API Translation** or **API Batch Translation** (your API key, with an estimate to approve).
2. Set which images to include and any instructions for your assistant.
3. **Copy starting prompt** and paste it into your assistant.
   It needs access to the game folder and the DazedTL folder.
4. Keep DazedTL open while it works.
   The same prompt picks up saved work later.

Follow progress and check the translations in the Project page's **History**.
Notes beside a translation flag text the AI wasn't sure about; check them against the original.

## Game updates

When a game gets a new official version, open **Game updates** on the Project page.
It sets the new version up as a separate copy, previews the changes, then applies the update to your translation.
**Discard release** drops an update you don't want.

## Backups and recovery

The Project page's **Backups** saves copies of the game and of your project files.
**Recover files…** restores a copy into a new folder; it never overwrites anything.
Backups live in the game's `.dazedtl` folder, so keep that folder with the game when you move it.

If DazedTL itself can't open, these commands, run from the DazedTL folder, list, check and restore backups; your coding assistant can run them for you.
On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`.

```bash
.venv/bin/python scripts/backups.py --game "/path/to/game" list
.venv/bin/python scripts/backups.py --game "/path/to/game" verify --id SNAPSHOT_ID
.venv/bin/python scripts/backups.py --game "/path/to/game" restore --id SNAPSHOT_ID --destination "/path/to/new-recovery-folder"
```

Don't edit or delete files inside the backup store by hand; backups share files with each other.

## API setup

In **Settings**, choose a provider, paste its API key and save.
Saving checks the connection by listing the provider's models, without generating any text; **Check again** repeats it, and **Model** picks one.
**Translation defaults** holds the target language and the advanced options.
Removing a connection stops its unfinished runs from resuming, so DazedTL tells you how many first.

**Advanced model options** apply to new estimates:

- Requests send 50 lines each by default.
- **Output token allowance** caps each reply at 32,768 tokens, or less when the model allows less.
- For OpenAI, **Batch token allowance** caps how much Batch work runs at once; raise it to your account's limit from [OpenAI Limits](https://platform.openai.com/settings/organization/limits).
- Prices come from the model catalog; models it doesn't know need your own rates, and 0 is fine for free models.

### OpenRouter

Save the key, then choose or type the full model ID, such as `anthropic/claude-sonnet-4.5`.
To use one hosting provider, edit the connection and choose **Host**; a chosen host never falls back to another, and **Automatic** lets OpenRouter choose.
OpenRouter Batches can take up to 24 hours and can't be cancelled once sent.
**Stop queued work** holds back what hasn't been sent, and **Continue queued work** resumes it.
Results missing from a finished Batch wait for **Retry collection** and are never sent again automatically.
Results DazedTL has downloaded stay available after OpenRouter deletes its copy.

## Updates

DazedTL checks for a new version once a day and downloads it in the background.
When one is ready, Settings shows a dot; **Settings > Updates** has **Restart to update**, which waits while a translation is running.
Projects, settings, API keys and runs are kept, and every file is checked against the release's signature first.
If an update fails, DazedTL keeps the version you had and says why.

**Go back to** returns to the previous version after a restart, and **Keep** cancels that.
The **Beta** channel offers test versions early.

## When something goes wrong

**Copy diagnostics** in the sidebar copies the app's version and recent errors for a problem report.
It never includes API keys, game text or what was sent to the AI.
Errors explained on screen aren't recorded, so include that message too.

If a page fails, its panel offers **Try again** and **Reload interface**; reloading keeps running translations going.
