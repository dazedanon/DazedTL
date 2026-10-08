# DazedTL

DazedTL translates games with AI.
You don't need to know how to program: DazedTL walks you through each step, and an AI coding assistant does the parts that need investigating.

## What you need

- An AI coding assistant, such as Claude Code or Codex.
  DazedTL gives you tasks to paste into it.
- An API key from OpenAI, Anthropic, Google Gemini, Mistral or OpenRouter, or a local model, for translating the game text.

## Two ways to translate

- **Guided steps**, for RPG Maker MV, MZ and VX Ace games: DazedTL leads you through five stages.
  Your API key translates the dialogue and database text, and your assistant handles names, plugins, images and other text it has to look into.
- **Assistant-led**, for any game: your assistant does the whole translation from one starting prompt, either by itself or through your API key.

## Install

1. Download the ZIP from [GitHub](https://github.com/dazedanon/DazedTL/archive/refs/heads/main.zip), [GitGud](https://gitgud.io/DazedAnon/dazedtl/-/archive/main/dazedtl-main.zip) or [git.dazedtl.dev](https://git.dazedtl.dev/dazed/DazedTL/archive/main.zip).
2. Unzip it somewhere easy to find, such as `C:\DazedTL`.
   Avoid OneDrive folders.
3. Open the folder and double-click **START.bat** on Windows, or run **START.sh** on Linux.
   If Windows says it protected your PC, click **More info**, then **Run anyway**.

There is nothing else to install.
The first start downloads what DazedTL needs, about 300 MB, and takes a few minutes.
After that, open DazedTL from the Start menu or desktop shortcut, or your Linux application menu.

## Get started

1. Open **Settings**, choose your AI provider and paste its API key.
2. Open **Project**, click **Open a game**, pick the game's folder and choose how to translate it.
3. Follow the steps, and paste each task DazedTL copies into your assistant.
   Nothing that costs money starts without showing you the estimate first.

The [user guide](docs/user-guide.md) explains every step.

## Updates

DazedTL updates itself.
When a new version is ready, **Settings** shows a dot: open its **Updates** tab and click **Restart to update**.
Your projects, settings and API keys are kept.

## Good to know

- WOLF RPG games don't have guided steps yet; translate them Assistant-led.
- On Ubuntu 24.04 and newer, the first start shows a one-time command to run in a terminal before DazedTL can open.
- macOS has a **START.command** launcher, but it hasn't been tested yet.
- If something goes wrong, click **Copy diagnostics** in the sidebar and include it when you report the problem.

Working on DazedTL itself? See the [development guide](docs/development.md).
