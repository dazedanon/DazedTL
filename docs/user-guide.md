# Using DazedTL

How to translate a game with DazedTL, step by step.
To install it, see the [README](../README.md#install).

## Before you start

1. In **Settings**, choose your AI provider, paste its API key and save; see [API keys and models](#api-keys-and-models).
2. Have an AI coding assistant ready, such as Claude Code or Codex, with access to the game's folder and the DazedTL folder; see [What you need](#what-you-need).
3. Keep the game as the developer released it, such as the ZIP you downloaded; see [Good habits](#good-habits).

## What you need

An **AI coding assistant**, also called an AI agent, is an AI chat that can read and change the files in a folder and run commands there.
[Claude Code](https://claude.com/product/claude-code) and [Codex](https://developers.openai.com/codex) are two.
Claude Code comes with Claude's paid plans and Codex with ChatGPT's plans; check each site for prices and limits.
DazedTL hands it the work that needs looking into, such as names, plugins and images, or in Assistant-led the whole game.
It asks before it changes files or runs commands unless you allow it to, so read what it wants to do.

An **editor**, or IDE, shows a folder's files and runs your assistant in a panel beside them.
[VS Code](https://code.visualstudio.com/) is free; [Cursor](https://cursor.com/) has free and paid plans with its own AI.
You can also run an assistant in its own app or a terminal.
Wherever it runs, open the game folder in it and give it access to the DazedTL folder: its tasks read the game and run DazedTL's project helper, which lives in the DazedTL folder.

## How it works

- **Projects.** Each game folder you open is a project: click **Open a game** on the Project page.
  A game you move or rename keeps its project; open it from its new folder.
- **Three methods.** A new game asks how to translate it: [Guided steps](#guided-steps) for RPG Maker MV, MZ and VX Ace, [Assistant-led](#assistant-led) or [Manual](#manual) for any game; see [Choosing a method](#choosing-a-method).
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

## Choosing a method

| | **Guided steps** | **Assistant-led** |
| --- | --- | --- |
| Games | RPG Maker MV, MZ and VX Ace | Any engine |
| Who translates | Your API key, stage by stage | Your assistant, from one starting prompt, through your API key or by itself |
| You decide | Each step, with an estimate before any paid work | The options at the start, and each estimate in the API modes |
| Your assistant's plan | Used for a few tasks | Used throughout |

Pick Guided steps for an RPG Maker game: you see and control each step.
Pick Assistant-led for other engines, such as WOLF RPG or TyranoScript, for a game whose text mostly sits in unusual plugins or scripts, or if you have no API key.
In Assistant-led your assistant follows Len's game-translation skills and writes its own tools for the game, so it can reach text in formats the Guided steps don't read.
Pick Manual if you have your own tools that extract a game's text and write it back.

## Good habits

DazedTL already does the safekeeping inside the game folder:

- Every change it makes is a [checkpoint](#checkpoints-and-undo) you can undo, and edits you make outside DazedTL get one of their own, so there is nothing to save by hand.
- Before it first changes the game, it records the original files in the game folder's Git repository.
- A new version of the game merges into your checkpoints through [Game updates](#game-updates).

That record lives only in this game folder on this computer, so two things are still yours to do:

- **Keep the developer's original download**, such as the ZIP, somewhere other than the game folder.
- **Push to a private remote repository** after each session of work, so a copy of your checkpoints exists off this computer; see [Make a remote repository](#make-a-remote-repository).
  The remote holds your translation and the files it changes, not the whole game.

Also:

- Work in one game folder: a copy of it opens as a new project.
- Translate a little and [playtest](#playtest-checklist) it before you translate the rest.

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
To ask for changes, open an image in **Compare images** and write **Revision notes**; they stay with the image, even one already in the game, until your assistant's results answer them.
**Copy revision task** there sends that image, and **Copy revision task** in the footer sends every noted image at once.

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
2. Check the game's **Languages**, whether to translate **Text in images**, the tools your assistant installs in the game, such as **GameUpdate**, and any instructions for your assistant.
   Changing a tool later takes effect the next time your assistant prepares the game.
3. Click **Copy starting prompt** and paste it into your assistant.
   It needs access to the game folder and the DazedTL folder.
4. Keep DazedTL open.
   **Progress** shows each phase and anything that needs you.
   In the API modes, approve your assistant's estimate there; it can't spend anything until you do.
   If your assistant stops, for example at a usage limit, paste the prompt into a new session and it picks up the saved work.
5. Use **Release** to build a clean game ZIP or save the patch, even before your assistant finishes: the patch's review lists what's left.

For RPG Maker games your assistant also fits the text to the game's windows and runs [Text QA](#4-check), with the playtest for MV and MZ games; the **Text QA** and **Playtest** tabs show the results.
To try again from scratch, stop your assistant and choose **Start over…** on **Progress**; the old attempt stays under Checkpoints.

Your assistant uses its own plan in every mode, so on a limited plan pick a smaller model or lower reasoning effort.

## Manual

Your own tools extract the game's text into a translation file and write the translations back; DazedTL translates the file with your API key.

1. On **Text**, load the file your tools wrote: JSON or CSV, one line per message with an ID, its scene, its source text and an empty translation.
   **Save example…** saves a file with every field, which the [translation contract](translation-contract.md#translation-files) describes; lines already translated in the file are kept.
2. Check **Options**, and the glossary on **Context**.
3. On **Progress**, click **Estimate cost**, then approve the estimate.
4. Click **Export translations…** and let your tools write the file into the game.

After the game changes, load a new extraction: lines whose ID and source stay the same keep their translation.

## Translation files

Under **Translation file** on the Project page, **Export…** saves every line with its translation as JSON, with the glossary, or as CSV for a spreadsheet.
**Import…** shows what a file changes, then takes its translations for the lines whose ID and source text match; the glossary only gains the terms it lacks.
In Guided steps the translations go into your working copies, so apply them in Translate.

## Playtest checklist

A run that ends without errors doesn't prove the game reads well, so play it after each Apply, and once more before you share it:

- Start a new game and play the scenes you translated; also open the menus, items, skills and shops.
- Look for Japanese left on screen, text running out of its box, and a name spelled two ways.
- Save and load once.
- Before sharing, test what **Release** builds on a fresh copy: unzip the clean game ZIP, or apply the patch ZIP to the developer's original.

When you find a problem, take a screenshot, note where it happened and give both to your assistant.
For MV and MZ games, **Playtest tools** helps you find a line's source; see [Check](#4-check).

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

## Make a remote repository

A remote repository is a copy of the game folder's checkpoints on a Git site such as [GitGud](https://gitgud.io) or [GitHub](https://github.com).
DazedTL doesn't create or push to one yet, so set it up once per game:

1. Sign in and create an empty project: on GitGud **New project > Create blank project**, on GitHub **New repository**.
   Make it **Private**, and don't add a README, license or `.gitignore`.
2. Copy its HTTPS address, such as `https://gitgud.io/your-name/your-game.git`.
3. Paste this into your assistant with your address:
   "In the game folder, add `ADDRESS` as the remote `origin` and push the `original` branch and the translation branch, `main`, or `translation` in games set up by older versions.
   Stop and ask if `origin` already exists."
4. If Git asks you to sign in, do it in the window it opens; never paste a password or token into your assistant.

After later work, ask your assistant to push again.
GitHub refuses files over 100 MB, and other sites have limits of their own; if a push fails on a big file, ask your assistant to explain the choices before anything is deleted.
Upload only what you may store: a private repository isn't permission to share someone's game.

## Publishing with GameUpdate

GameUpdate updates players to your latest translation from a public Git repository on GitGud, GitHub or a Forgejo server such as Codeberg.
Set up, or saving **Options** in Manual, adds `GameUpdate.bat`, its scripts and a `README.md` for players to the game.

1. In **Settings > GameUpdate**, choose the site and enter the owner of your repositories, such as `dazed-translations`.
   Leave the owner empty if you don't use GameUpdate.
2. Confirm the game's repository under **GameUpdate**, in the **Release** task or on **Options**; DazedTL fills it in from the game's Git remote when it can.
3. Push the translation to that repository before you build a ZIP; see [Make a remote repository](#make-a-remote-repository), and make it public when you release.
   Otherwise GameUpdate stays off in that ZIP, since it can't tell which version players start from.

If the site refuses its download, GameUpdate uses Git, which Linux players must install.
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
- **DeepSeek** and **OpenCode** translate Live only; DeepSeek costs half [off-peak](https://api-docs.deepseek.com/quick_start/pricing), on Go too.
- **OpenCode:** **Plan** picks what pays.
  **Go subscription** bills your plan's allowance; a used-up limit fails requests until it resets, unless Extra Usage is on.
  Go's DeepSeek needs **Global** under Regions in the workspace's Privacy settings, and Muse Spark needs **Allow paid endpoints that train on request data** turned on.
  **Pay-as-you-go balance** bills your Console balance; free models work only in OpenCode's app and aren't listed.
- The estimate leaves out Kimi and DeepSeek thinking, billed as output; Thinking effort **Off** stops DeepSeek's.

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

## Common problems

**No speaker names found, or names missing before you translate.**
On **Context > Names & glossary**, copy the task: your assistant identifies the game's **Speaker formats** first.
Then **Speaker names > Open scan > Run local scan** collects the names, and **View formats** shows what was found; its **Settings** tab turns kinds of names on or off, such as **Face names**.
Do this before you translate **Maps & events**.

**A plugin's text doesn't show up translated.**
Text from a plugin command or script in an event comes from **Event text sources**: copy its investigation task again, then translate **Other event text**.
A menu or label a plugin draws itself belongs to **Plugin files**: copy its task again and tell your assistant where you saw the text.

**Japanese left after Apply.**
Run [Text QA](#4-check): its **Never translated** list shows text still in Japanese, and for MV and MZ games the playtest names the task that translates what players see.
Lines that failed keep their original text until you translate them again; text inside pictures is the **Images** task.

**The assistant can't see the game folder or reach DazedTL.**
Open the game folder in your editor, give your assistant access to the DazedTL folder, and start a new chat.
If it says the local DazedTL request failed while DazedTL is open, its sandbox is blocking the connection: approve the helper command when your assistant asks for permission.

## When something goes wrong

Click **Report a problem** in the sidebar and paste the report on [Discord](https://discord.gg/StsRWHPupu).
It fills in your DazedTL version, system, open game and recent errors; add what happened, with any message on screen, and the steps that led to it.
If something is stuck, copy the report while it's still stuck.
If you're asked for more detail, **Settings > Updates** has **Copy full diagnostics**.
Apart from the game's name, it never includes API keys or game text.

If a page fails, its panel offers **Try again** and **Reload interface**; reloading keeps running translations going.

## Contributing

If you and your assistant fixed something in your game that DazedTL got wrong, such as speaker names it missed or plugin text it skipped, share it so DazedTL can handle games like it by itself.
Click **Share a fix** in the sidebar with the game open and paste the task into the assistant chat where you made the fix.
It fills in your DazedTL version, system and game, and your assistant writes a short report: the problem, what changed, how you tested it in the game and whether other games share the pattern.
Read it over, then post it on [Discord](https://discord.gg/StsRWHPupu).
It leaves out API keys and long stretches of game text.

If you know Git, [Development](development.md#contributing-a-change) says how to send a change.
