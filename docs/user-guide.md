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

The other tabs are **History** (runs, estimates and other activity), **Versions** and **Backups**.

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
It finds the speakers, running jokes and recurring terms, lists the names with a free local scanner, and writes the glossary, character notes and game context.
In RPG Maker MZ games the scanner also finds likely **Speaker slips**: boxes in the original game whose nameplate or face likely shows the wrong speaker, such as a nameplate on a sound effect.
Your assistant checks each one in its scene and fixes the real ones; **View names** shows what it fixed and why it kept the rest.
Edit what it wrote in **Guidance**.
**Add game folder** lets an earlier game in a series supply terms; copy the task again afterwards.
**Thorough investigation** looks for names, running jokes and speech habits in three independent passes instead of one, and that step then uses about three times as much of your assistant's plan.

**Event text sources**: copy the investigation to your assistant.
It finds which variables, plugin commands and scripts hold text players see and turns those on.
It also decides how English words stay together in plugin commands and which internal values, such as placeholders, stay untranslated.
Change any choice under **Source choices**; **Other event text** in Translate translates them later.

**Line widths** fills in from your assistant's measurements, which it checks in the running game, and you can change them.
Message rows is how many rows one message window shows; Text QA keeps its corrections within it.

**Cost estimate** shows what translating the whole game costs with your API key before you translate anything.
Click **Estimate cost**: it estimates Database files, Maps & events and Other event text over all their files, with the model shown beside it, and lists each task's cost.
Estimating is free and translates nothing; for Claude models it uses Anthropic's free token count.
On a large game this can take several minutes: each task shows how far it has got and about how long is left, and a finished estimate says how long it took.
The other tasks use your assistant's plan, not your API key.
If you change the guidance, the source choices, the game's files or the model, or update DazedTL, the estimate reads **Outdated**; click **Estimate again**.
Until then **Estimate again** stays off, since it would give the same result.

### 3. Translate

Translate has five tasks.

**Database files** and **Maps & events** translate with your API key:

1. Pick the files; all of them start selected.
   Translate the database first, and try a small early scene before the rest.
2. Choose **Batch** (often half the price, but can take hours) or **Live** (results arrive as you watch), and the model.
3. Click **Translate**, check the estimate and approve it.
   Until the estimate is ready, its window shows each step, how far it has got and about how long is left.
   If you decline or close it, clicking **Translate** again reuses it while the files and settings are unchanged.
   With **Batch**, names and labels the glossary lacks are translated first with Live, after their own review; they join the glossary even if you then decline the Batch.
4. Click **Apply** to write the translations into the game.

Approved Batch work carries on after DazedTL restarts.
**Reload from game…** starts selected files over from the game's current text.

**Other event text** translates the sources chosen in **Event text sources**, like the other files.

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

All Check tasks are optional:

- **Line width check** finds applied lines wider than the saved line widths and rewraps them; **Edit settings** chooses what it covers.
- **Text QA**: **Start text QA** copies the task, and your assistant reviews the translated text and applies the corrections it verifies.
  A correction too wide for its box is rewrapped to the Line widths saved when QA started.
  QA also opens the game's screens, such as its menus, item lists and shop, without changing the game, and shortens names and commands the game squeezes or cuts off; **Review them** lists such text QA can't change, such as a plugin's menu.
  Answer the questions it can't settle on the page; each correction is listed with **Undo**, and an undone one with **Apply again**; **Review them** lists the lines QA did not cover.
  That includes Japanese that was never translated, which QA can't review, with whether players can see it; translate what they can in its own task, such as **Plugin files**.
  A correction that changes several lines of one scene, such as narration that switches tense, is listed and undone as one.
  To take out every correction at once, inspect **Apply QA corrections** in the Project page's **History** and choose **Review restore**.
- **Playtest** (MV and MZ): **Run playtest** has DazedTL check the game's files and play it in a hidden window for a few minutes, writing nothing into the game.
  It lists crashes, Japanese left in the game, text that doesn't fit and names or codes the translation lost, each with the task that fixes it; **View** shows what the game looked like when it found the problem.
  Problems in translated text go to Text QA, which corrects them when it runs, so after fixing, run the playtest again: it counts what was fixed since the last run.
  **1 not reached** lists what the playtest could not get to; your assistant can add those places.

**Playtest tools** at the top installs TL Inspector and Forge to help you playtest MV and MZ games.
Apply and playtest an early scene before translating everything.

Applying replaces the game's files with the translations.
If you edit a file in the game afterwards, applying it again replaces your edits, and the review names those files.
If applying stops midway, **Review restore** puts the files back.

### 5. Release

**Release** builds a clean game ZIP or a patch ZIP with only the changed files.
The clean game ZIP holds the game and its translation; files added to the game folder while you worked, such as notes or downloads, stay out; **View files & exclusions** lists them.
Save it outside the game folder.
Translations that aren't in the game yet need **Apply** first.
The ZIP shows **Outdated** once the game changes; build it again to include the changes.
To let players update from a public repository, see [Publishing with GameUpdate](#publishing-with-gameupdate).
**Player walkthrough** copies an optional task for your assistant to write a walkthrough for players.

### RPG Maker VX Ace

Set up's **Convert Ace data** unpacks an encrypted `Game.rgss3a` and converts the game data so it can be translated.
**Review native Ace packing**, in Check or Release, writes the translations back.
A patch ZIP for an encrypted game carries a rebuilt `Game.rgss3a`, so players replace one file.
GameUpdate can't update an encrypted game, so share a new patch for each update instead.

## Assistant-led

1. In **Options**, choose who translates:
   - **API Batch** is recommended: your API key translates in one provider job, at half the Live price where the provider offers it.
   - **Live API** sends one request at a time at the full price; new games start on it when your connection can't run Batch.
   - **Assistant only** needs no API key, but your assistant translates every line itself, which uses far more of its plan.

   The API modes need a connection in Settings, and your assistant asks you to approve its estimate before anything is sent.
2. Set which images to include and any instructions for your assistant.
   **Thorough investigation** looks for names, running jokes and speech habits in three independent passes instead of one, and that step then uses about three times as much of your assistant's plan.
3. **Copy starting prompt** and paste it into your assistant.
   It needs access to the game folder and the DazedTL folder.
   It works on its own and asks you only when it must, such as to approve spending.
4. Keep DazedTL open while it works.
   **Progress** shows its phases, anything it needs from you and any API run.
   With **Image text** on, it also finds the images with text, translates them and puts them in the game; **Images** shows where that stands and lets you change the list.
   For RPG Maker games it also runs text QA: **Text QA** appears once it starts, lists each correction with **Undo** and asks you only what it can't settle, which **Progress** points out.
   For MV and MZ games it runs the playtest too, which **Playtest** shows once it has.
   When your assistant asks you to approve an API estimate, answer it or use the approve button on **Progress**.
   If you approve there, tell your assistant so it waits for the results; **Progress** reminds you until it has checked in.
   Changing your API settings or the mode makes a waiting estimate out of date, so ask your assistant for a new one.
   If it goes quiet, for example at a usage limit, paste the prompt into a new session; it picks up the saved work.
   DazedTL counts the game's Japanese text itself, and **Progress** shows whether your assistant extracted all of it; it can't leave out maps or scenes on its own.
   In **Assistant only**, lines your assistant won't translate appear under **Declined lines** while it carries on.
   Estimate them with your API connection and approve, or copy a prompt that has another coding assistant translate only those lines; your assistant picks up the translations once they're saved.
5. To try again from scratch, stop your assistant and choose **Start over…** on **Progress**.
   It puts back the original game files and moves the attempt to `.dazedtl/archived`; backups, save games, Image Manager work and your options stay, and so do the glossary and notes unless you clear **Keep glossary and notes**.

Your assistant's session uses its own plan in every mode, so on a limited plan pick a smaller model or lower reasoning effort.

Follow progress and check the translations in the Project page's **History**.
Notes beside a translation flag text the AI wasn't sure about; check them against the original.

## Publishing with GameUpdate

GameUpdate lets players update to your latest translation from its public Git repository on GitGud, GitHub or a Forgejo server such as Codeberg.
It is separate from [Versions](#versions), which merge a new official version of the game.

Set up adds `GameUpdate.bat` for Windows, `GameUpdate_linux.sh` for Linux, the `gameupdate` folder and a `README.md` that tells players how to patch and becomes the repository's front page.
MV and MZ games also get a startup check that warns players when the repository has a newer version and links to it; offline or after an error, the game starts as usual.
Set up never replaces a game's existing `README.md`; to get the current one, delete it and choose **Recreate GameUpdate files** under **Preparation tools**.

DazedTL connects each game to its repository through `gameupdate/patch-config.txt`, which it writes and commits with each translation version:

1. In **Settings > GameUpdate**, choose the forge and host and enter the owner of your patch repositories, such as `dazed-translations`.
   Leave the owner empty if you don't publish with GameUpdate.
2. Each game's repository is under **GameUpdate** in the **Release** task, or on **Options** for Assistant-led.
   DazedTL fills it in from the game's `origin` remote when that belongs to the owner; otherwise type it and **Save**.
   Until it's known, Release waits for it.

The status below it says whether the file is **Ready to publish**, **Not committed yet** (the next translation version, such as building a patch ZIP, commits it) or **Changed outside DazedTL**.
For a file someone edited, **Keep the file** keeps its values for this game and **Rewrite the file** puts DazedTL's back; **Follow Settings** later drops what the game kept.
A warning appears when players would download from a site or repository this game's Git remotes don't point to.

The file holds these keys:

| Key | Meaning |
| --- | --- |
| `forge` | `gitlab` (the default), `github` or `forgejo` (`gitea` also works) |
| `host` | The host name only; defaults to `gitgud.io`, `github.com` or `codeberg.org` to match `forge` |
| `username` | The user, organization or group that owns the repository (`owner` and `org` also work) |
| `repo` | The repository name |
| `branch` | The branch players update from |

A file with only `username`, `repo` and `branch` uses GitLab on `gitgud.io`.

Before building a clean game ZIP for players, save the translation version and push it to the repository branch it tracks.
**Release** then writes that commit into the ZIP's `gameupdate/previous_patch_sha.txt`, so GameUpdate knows which version players start from; the game folder itself doesn't change.
Without the pushed commit, the clean ZIP leaves out `patch-config.txt`, as patch ZIPs always do, so GameUpdate stays off in it.

## Versions

When a game gets a new official version, open **Versions** on the Project page.
Choose the folder the developer released, either the complete game or a patch of files to copy over it; DazedTL says which it looks like, and you can change that.
It sets the new version up as a separate copy, previews the changes, then applies the update to your translation.
Lines the developer left as they were keep their translations, even beside new or changed ones.
The preview counts the lines to translate and the translations that go back to Japanese; open a file to see its lines before and after.
A patch keeps every game file it doesn't include, but it can't remove files the developer deleted.
Steps above the update show where it stands, and the versions the game had are listed below.
**Discard release** drops an update you don't want.

Once the update is in the game, Guided steps list the tasks it changed, such as **Maps & events**; each opens with the changed files selected.
Files you translated before read **Outdated** there, so **Reload from game…** brings in their new text, and translating them again only sends the Japanese lines.
For Assistant-led, **Copy post-update task** gives your assistant the update to translate.

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

## Notifications

**Settings > Notifications** can call you back to DazedTL with a sound, a desktop notification, or both; both start off.
They come when a translation or other step that took more than a few seconds ends, when work waits for your approval, and when your assistant hands back a task, asks you something or finishes an Assistant-led run.
The sound plays even while DazedTL is in front, so you hear it from across the room; the desktop notification shows only while DazedTL is in the background, clicking it brings DazedTL back, and coming back clears it.
**Sound** plays the built-in chime or a file you choose, such as an MP3 or WAV, for up to 10 seconds; DazedTL keeps its own copy, so you can move or delete the original.
**Test notification** tries what you chose.

## Updates

DazedTL checks for a new version once a day and downloads it in the background.
When one is ready, Settings shows a dot; **Settings > Updates** shows what's new in it and has **Restart to update**, which waits while a translation is running.
After the restart, the same tab shows what changed since the version you had, followed by the notes of every earlier version.
Projects, settings, API keys and runs are kept, and every file is checked against the release's signature first.
If an update fails, DazedTL keeps the version you had and says why.

**Go back to** returns to the previous version after a restart, and **Keep** cancels that.
The **Beta** channel offers test versions early.

## When something goes wrong

**Copy diagnostics** in the sidebar copies the app's version and recent errors for a problem report.
If something stays stuck, copy diagnostics while it is still stuck; after a minute they say where it is waiting.
It never includes API keys, game text or what was sent to the AI.
Errors explained on screen aren't recorded, so include that message too.

If a page fails, its panel offers **Try again** and **Reload interface**; reloading keeps running translations going.
