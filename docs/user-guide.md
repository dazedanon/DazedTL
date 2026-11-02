# Using DazedTL

How to translate a game with DazedTL, step by step.
To install it, see the [README](../README.md#install).

## Before you start

1. In **Settings**, choose your AI provider, paste its API key and save; see [API keys and models](#api-keys-and-models).
2. Have an AI coding assistant ready, such as Claude Code or Codex, with access to the game's folder and the DazedTL folder.

## How it works

- **Projects.** Each game folder you open is a project: click **Open a game** on the Project page.
  A game you move or rename keeps its project; open it from its new folder.
- **Two methods.** A new game asks how to translate it: [Guided steps](#guided-steps) for RPG Maker MV, MZ and VX Ace, or [Assistant-led](#assistant-led) for any game.
  **Change method** on the Project page switches later and keeps your work.
- **Assistant tasks.** Some steps copy a task for your assistant.
  Paste it in and keep DazedTL open: the results show up by themselves.
  Copying a task never costs anything.
- **Costs.** Anything that uses your API key shows an estimate first, and nothing is charged until you approve it.
- **Undo.** Every change DazedTL makes to the game is a [checkpoint](#checkpoints-and-undo) you can undo, so there is nothing to save by hand.

Tasks use the same words everywhere:

| Word | Meaning |
| --- | --- |
| **Waiting** | The task is with your assistant. |
| **Needs review** | Results need your decision. |
| **Ready to apply** | Results are ready to go into the game. |
| **Applied** | The results are in the game. |
| **Done** | Finished work that doesn't change the game. |
| **Outdated** | Something it was based on changed; redo it. |
| **Blocked** | It can't continue; the detail beside it says why. |

## Guided steps

A Guided translation has five stages: **Set up → Context → Translate → Check → Release**.
On the Project page, **Continue** opens the next unfinished task; optional tasks say so and never hold you up.
**Assistant tasks**, opened from the count in the top bar, lists what you've handed to your assistant and where each task stands.

### 1. Set up

Click **Set up this game** and answer its two questions: the game's version, and whether it already has translations.
DazedTL prepares the game files and keeps a copy of the originals, so every change can be undone and later versions of the game can be merged in.
For VX Ace games, it also converts the game's data, unpacking an encrypted `Game.rgss3a`, so it can be translated.

**Languages** shows what the game translates from and into.
New games start with the languages in **Settings > Translation defaults**, Japanese to English unless you change them.
**Change…** picks this game's own, until its first translation.
To translate a game into another language later, open a fresh copy of it as a new project.
For a Chinese or Japanese target, measure **Line widths** before you apply anything, since the stock widths are set for English.

### 2. Context

| Task | What to do |
| --- | --- |
| **Names & glossary** | Copy the task to your assistant. It writes the glossary, character notes and game context; edit them in **Guidance**. |
| **Event text sources** | Copy the task. Your assistant finds text the game shows through plugins and scripts; change its choices under **Source choices**. |
| **Line widths** | Optional: copy the task, and your assistant measures the game's text boxes. Adjust the widths if you like; saving rewraps text already applied. |
| **Cost estimate** | Click **Estimate cost** to see what translating the whole game will cost. Estimating is free. |

### 3. Translate

**Database files** and **Maps & events** translate with your API key:

1. Pick the files.
   Start with the database and a short early scene, and playtest them before you translate the rest.
2. Choose the model, and **Batch** (often half the price, but it can take hours) or **Live** (results arrive as you watch).
3. Click **Translate**, check the estimate and approve it.
   Approved Batch work carries on if DazedTL restarts.
4. Click **Apply** to write the translations into the game.

**Other event text** translates what **Event text sources** found, the same way.

**Plugin files**: copy the task, and your assistant translates the text in the game's plugins, or in a VX Ace game its scripts' menus and messages.
Click **Apply to game** when it's done.

**Images** has four steps, and the filled button is always the next one:

1. **Investigate** (optional): your assistant recommends the images with text players read.
2. **Choose** the images to translate.
3. **Translate**: copy the task, and your assistant edits copies of the images.
4. **Apply**: check the results and click **Apply to game**.

To letter an image yourself, tick it and choose **More > Edit text…**.

If a run fails, a banner says why, and **Run history > Inspect** shows each request and the AI's reply.
Lines that failed keep their original text until you translate them again.

### 4. Check

**Text QA** is optional.
Click **Start text QA** and paste the task into your assistant: it reviews the translation, fixes what it can verify and asks you only what it can't settle.
Every correction is listed with **Undo**.

For MV and MZ games, the same task also playtests the game in a hidden window without changing it, and your assistant fixes what it finds, such as untranslated text, text cut off on screen and crashes.
The **Playtest** panel shows what's left.

**Playtest tools** installs TL Inspector and Forge to help you playtest MV and MZ games yourself.
TL Inspector stays on your computer and never goes into the translation you release.

### 5. Release

**Release** builds a ZIP for players: a clean game ZIP with the whole translated game, or a patch ZIP with only the changed files.
Apply your translations first, and save the ZIP outside the game folder.
If the game changes afterwards, the ZIP reads **Outdated**; build it again.
**Player walkthrough** copies an optional task for your assistant to write a walkthrough for players.
To let players update from your repository, see [Publishing with GameUpdate](#publishing-with-gameupdate).

For VX Ace games, name the clean game ZIP in English letters: the name becomes the game's folder, and the game won't start on English Windows from a folder named in Japanese.

## Assistant-led

Your assistant translates the whole game from one starting prompt.

1. On **Options**, choose who translates:
   - **API Batch** (recommended): your API key, usually at half the Live price.
   - **Live API**: your API key at the full price.
   - **Assistant only**: no API key, but your assistant translates every line itself, which uses far more of its plan.
2. Check the game's **Languages**, whether to translate images (**Image text**), and any instructions for your assistant.
3. Click **Copy starting prompt** and paste it into your assistant.
   It needs access to the game folder and the DazedTL folder.
4. Keep DazedTL open.
   **Progress** shows each phase and anything that needs you.
   In the API modes, approve your assistant's estimate there; it can't spend anything until you do.
   If your assistant stops, for example at a usage limit, paste the prompt into a new session and it picks up the saved work.
5. When the **Patch** phase shows the ZIP, use **Release** to build a clean game ZIP or save the patch.

For RPG Maker games your assistant also fits the text to the game's windows and runs [Text QA](#4-check), with the playtest for MV and MZ games; the **Text QA** and **Playtest** tabs show the results.
To try again from scratch, stop your assistant and choose **Start over…** on **Progress**; the old attempt stays under Checkpoints.

Your assistant uses its own plan in every mode, so on a limited plan pick a smaller model or lower reasoning effort.

## Checkpoints and undo

Every change DazedTL makes to the game is a checkpoint on the Project page's **Checkpoints** tab, newest first.
**View changes** shows each line before and after, and the **…** menu has:

- **Undo this change** takes out only that change.
- **Go back to here** puts the game back as it was after that change.
- **Save a copy…** saves the whole game as it was then into a new folder.

Undoing is a checkpoint too, so it can be undone.
Edits you make to the game outside DazedTL become a checkpoint of their own.
In **History**, **Undo** takes out a whole batch at once, such as Text QA's corrections or the playtest's fixes.

### Game updates

When the developer releases a new version of the game, choose **Start game update** on **Checkpoints** and pick the new version's folder, either the complete game or a patch.
DazedTL previews the changes, then merges them into your translation: lines the developer didn't change keep their translations.

- Guided steps list the tasks the update changed, with the changed files selected: **Reload from game…** brings in their new text, and translating sends only the untranslated lines.
- In Assistant-led, click **Copy post-update task** and paste it into your assistant.

If an update stops partway, **Checkpoints** offers to finish or cancel it.

### Backups from before checkpoints

Older versions of DazedTL kept backups in the game's `.dazedtl/backups` folder.
To list, check or restore them, run these from the DazedTL folder, or ask your assistant to; on Windows, use `.venv\Scripts\python`.

```bash
.venv/bin/python scripts/backups.py --game "/path/to/game" list
.venv/bin/python scripts/backups.py --game "/path/to/game" verify --id SNAPSHOT_ID
.venv/bin/python scripts/backups.py --game "/path/to/game" restore --id SNAPSHOT_ID --destination "/path/to/new-recovery-folder"
```

Don't edit or delete files in the backup folder by hand: backups share files.

## Publishing with GameUpdate

GameUpdate lets players update to your latest translation from a public Git repository on GitGud, GitHub or a Forgejo server such as Codeberg.
Set up adds it to the game: `GameUpdate.bat`, `GameUpdate_linux.sh`, the `gameupdate` folder and a `README.md` for players.

1. In **Settings > GameUpdate**, choose the site and enter the owner of your repositories, such as `dazed-translations`.
   Leave the owner empty if you don't use GameUpdate.
2. Confirm the game's repository under **GameUpdate** in the **Release** task, or on **Options** for Assistant-led; DazedTL fills it in from the game's Git remote when it can.
3. Push the translation to that repository before you build a ZIP.
   Otherwise GameUpdate stays off in that ZIP, since it can't tell which version players start from.

GameUpdate can't update an encrypted VX Ace game, so share a new patch for each update instead.

DazedTL saves the repository in the game's `gameupdate/patch-config.txt`:

| Key | Meaning |
| --- | --- |
| `forge` | `gitlab` (the default), `github` or `forgejo` (`gitea` also works) |
| `host` | The host name only; defaults to `gitgud.io`, `github.com` or `codeberg.org` to match `forge` |
| `username` | The user, organization or group that owns the repository (`owner` and `org` also work) |
| `repo` | The repository name |
| `branch` | The branch players update from |

## API keys and models

In **Settings**, choose a provider, paste its API key and save.
Saving checks the connection for free, and **Model** picks the model.
**Translation defaults** holds the languages new games start with and the **Advanced model options**, such as the model's thinking effort.
Models DazedTL doesn't know need your own prices there; 0 is fine for free models.
For OpenAI, raise **Batch token allowance** to your account's limit from [OpenAI Limits](https://platform.openai.com/settings/organization/limits).

- **OpenRouter:** enter the full model ID, such as `anthropic/claude-sonnet-4.5`; **Host** pins one hosting provider.
  Its Batches can take up to 24 hours and can't be cancelled once sent.
- **Kimi:** Batch works with Kimi K2.6 and K2.7 Code, at 40% off; Kimi K3 translates Live only.
- **DeepSeek:** no Batch, so it translates Live; outside its [peak hours](https://api-docs.deepseek.com/quick_start/pricing) it costs half.
- Kimi and DeepSeek models think before they answer, which is billed as output and isn't in the estimate.

## Notifications

**Settings > Notifications** can call you back when a translation ends, when work waits for your approval, and when your assistant hands back a task or asks you something.
Choose a sound, a desktop notification, your phone, or any of them.

For your phone, install the free [ntfy](https://ntfy.sh) app, tap **+** and type the **Phone topic** DazedTL shows.
Keep the topic to yourself, since it's the only password.
Phone notifications come only while DazedTL is open on your computer.

## Updates

DazedTL updates itself.
When a new version is ready, **Settings** shows a dot: open **Updates** and click **Restart to update**.
Your projects, settings and API keys are kept.
**Go back to** returns to the previous version, and the **Beta** channel gets test versions early.

## When something goes wrong

Click **Report a problem** in the sidebar and paste the report on [Discord](https://discord.gg/StsRWHPupu).
It fills in your DazedTL version, system, open game and recent errors; add what happened, with any message on screen, and the steps that led to it.
If something is stuck, copy the report while it's still stuck.
If you're asked for more detail, **Settings > Updates** has **Copy full diagnostics**.
Apart from the game's name, it never includes API keys or game text.

If a page fails, its panel offers **Try again** and **Reload interface**; reloading keeps running translations going.
