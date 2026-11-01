<p align="center">
  <img src="resources/forum-banner.gif" width="519" alt="DazedTL, AI Translation Tool">
</p>

<p align="center">
  <b>Translate games with AI. No programming needed.</b><br>
  DazedTL walks you through each step, and an AI coding assistant does the parts that need investigating.
</p>

<p align="center">
  <a href="CHANGELOG.md"><img src="https://img.shields.io/github/v/tag/dazedanon/DazedTL?sort=semver&label=version&color=5ee0c4&labelColor=1b2a2e" alt="Latest version"></a>
  <img src="https://img.shields.io/badge/runs%20on-Windows%20%7C%20Linux-5ee0c4?labelColor=1b2a2e" alt="Runs on Windows and Linux">
  <a href="LICENSE.md"><img src="https://img.shields.io/badge/license-MIT-5ee0c4?labelColor=1b2a2e" alt="MIT license"></a>
  <a href="https://discord.gg/StsRWHPupu"><img src="https://img.shields.io/discord/1124349971097976903?label=discord&logo=discord&logoColor=white&color=5ee0c4&labelColor=1b2a2e" alt="Discord: people online"></a>
  <a href="https://dazedanon.gumroad.com/l/dazedanon"><img src="https://img.shields.io/badge/support-Gumroad-5ee0c4?logo=gumroad&logoColor=white&labelColor=1b2a2e" alt="Support DazedTL on Gumroad"></a>
</p>

<p align="center">
  <a href="#install"><b>Install</b></a> ·
  <a href="docs/user-guide.md"><b>User guide</b></a> ·
  <a href="CHANGELOG.md"><b>What's new</b></a> ·
  <a href="https://discord.gg/StsRWHPupu"><b>Discord</b></a>
</p>

<p align="center">
  <img src="docs/media/translate.webp" width="880" alt="DazedTL translating a game's maps: the cost estimate is approved, each file translates live, and the translations are applied to the game">
</p>

## What it does

DazedTL translates a game's text with your AI provider and writes it back into the game's own files, so the game itself plays in your language.

<p align="center">
  <img src="docs/media/game.webp" width="880" alt="The same scene of an RPG Maker game before and after: the village chief's line in Japanese, then in English with his name translated">
</p>

### Two ways to translate

- **Guided steps**, for RPG Maker MV, MZ and VX Ace games: DazedTL leads you through five stages.
  Your API key translates the dialogue and database text, and your assistant handles names, plugins, images and other text it has to look into.
- **Assistant-led**, for any game: your assistant does the whole translation from one starting prompt, either by itself or through your API key.

<p align="center">
  <img src="docs/media/project.webp" width="880" alt="The Project page: lines translated, files applied and cost so far, and the tasks of the five stages with the next step highlighted">
</p>

### Hand the tricky parts to your assistant

Names, plugins, images and other text that needs looking into become tasks DazedTL copies for your assistant.
Paste one in and keep DazedTL open: the results show up by themselves, and DazedTL checks every change before you apply it.

<p align="center">
  <img src="docs/media/assistant.webp" width="880" alt="Handing Plugin files to an assistant: the task is copied, waits while the assistant works, comes back ready to apply, and is applied to the game">
</p>

### See the cost before you pay

With a frontier model such as Claude Opus 5.5, an average-sized game costs about $20–30 to translate; a small one can cost under $10, and a very large one $50 or more.
Anything that uses your API key shows an estimate first, and nothing is charged until you approve it.
Batch translation is often half the price of Live, if you can wait.

<p align="center">
  <img src="docs/media/estimate.webp" width="880" alt="The review before a Live translation: the model, the estimated cost, requests and tokens, and the files it covers, with Start and Decline">
</p>

### Have it checked

Text QA has your assistant review the translation, and play MV and MZ games, fixing what it finds.
You answer only what it can't settle, and every correction can be undone.

<p align="center">
  <img src="docs/media/qa.webp" width="880" alt="Text QA's result: a stilted line corrected for fluency, showing the Japanese, the new and old English with the changed words marked, the reason, and Undo">
</p>

### Share it

**Release** builds a clean game ZIP, or a patch ZIP with only the changed files.
Every change DazedTL makes to the game is a checkpoint you can undo, and a new version of the game merges into your translation.

<p align="center">
  <img src="docs/media/release.webp" width="880" alt="The Release step: a clean game ZIP or a patch ZIP, its name and folder, and an optional walkthrough for players">
</p>

## What you need

- An AI coding assistant, such as Claude Code or Codex.
  DazedTL gives you tasks to paste into it.
- An API key from OpenAI, Anthropic, Google Gemini, Mistral, Kimi, DeepSeek or OpenRouter, or a local model, for translating the game text.

## Install

1. Download the ZIP from [GitHub](https://github.com/dazedanon/DazedTL/archive/refs/heads/main.zip), [GitGud](https://gitgud.io/DazedAnon/dazedtl/-/archive/main/dazedtl-main.zip) or [git.dazedtl.dev](https://git.dazedtl.dev/dazed/DazedTL/archive/main.zip).
2. Unzip it somewhere easy to find, such as `C:\DazedTL`.
   Avoid OneDrive folders.
3. Open the folder and double-click **START.bat** on Windows, or run **START.sh** on Linux.
   If Windows warns that the publisher could not be verified, click **Run**; if it says it protected your PC, click **More info**, then **Run anyway**.

There is nothing else to install.
The first start downloads what DazedTL needs, about 300 MB, and takes a few minutes.
After that, open DazedTL from the Start menu or desktop shortcut, or your Linux application menu.

## Get started

1. Open **Settings**, choose your AI provider and paste its API key.
2. Open **Project**, click **Open a game**, pick the game's folder and choose how to translate it.
3. Follow the steps, and paste each task DazedTL copies into your assistant.

The [user guide](docs/user-guide.md) explains every step.

## Updates

DazedTL updates itself.
When a new version is ready, **Settings** shows a dot: open its **Updates** tab to see what's new and click **Restart to update**.
Your projects, settings and API keys are kept.
The [changelog](CHANGELOG.md) lists what changed in every version.

## Good to know

- DazedTL translates between languages written in different scripts, such as Japanese to English or English to Japanese; pairs in the same script, such as English to Spanish, aren't supported yet.
- WOLF RPG games don't have guided steps yet; translate them Assistant-led.
- On Ubuntu 24.04 and newer, the first start shows a one-time command to run in a terminal before DazedTL can open.
- macOS has a **START.command** launcher, but it hasn't been tested yet.
- If something goes wrong, click **Copy diagnostics** in the sidebar and include it when you report the problem on [Discord](#community).

## Community

- Ask questions, share your translations and report problems on the [AI Translations Discord](https://discord.gg/StsRWHPupu).
- DazedTL is free. If it helps you, you can support it with any amount on [Gumroad](https://dazedanon.gumroad.com/l/dazedanon).

Working on DazedTL itself? See the [development guide](docs/development.md).
