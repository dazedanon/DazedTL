# DazedTL

DazedTL translates games with AI.
You don't need to know how to program: the app walks you through each step, and you bring an API key from an AI provider.

- **RPG Maker MV, MZ and VX Ace** games get a guided, step-by-step translation.
- **Any other game** can be translated by an AI coding assistant, such as Claude Code or Codex, while DazedTL keeps track of the work.
- Works with OpenAI, Anthropic, Google Gemini, Mistral, OpenRouter or a local model.

## Install

1. Download the ZIP from [GitGud](https://gitgud.io/DazedAnon/dazedtl/-/archive/main/dazedtl-main.zip) or [git.dazedtl.dev](https://git.dazedtl.dev/dazed/DazedTL/archive/main.zip).
2. Unzip it somewhere easy to find, such as `C:\DazedTL`.
   Avoid OneDrive folders.
3. Open the folder and double-click **START.bat** on Windows, or run **START.sh** on Linux.
   If Windows says it protected your PC, click **More info**, then **Run anyway**.

There is nothing else to install.
The first start downloads what DazedTL needs, about 300 MB, and takes a few minutes.
After that, open DazedTL from the Start menu or desktop shortcut, or your Linux application menu.

## Get started

1. Open **Settings**, choose your AI provider and paste its API key.
2. Open **Project**, click **Open a game** and pick the game's folder.
3. Follow the steps.
   Nothing that costs money starts without showing you the estimate first.

The [user guide](docs/user-guide.md) explains every step.

## Updates

DazedTL updates itself.
When a new version is ready, **Settings** shows a dot: open its **Updates** tab and click **Restart to update**.
Your projects, settings and API keys are kept.

## Good to know

- WOLF RPG games don't have a guided translation yet; use an AI coding assistant for them.
- On Ubuntu 24.04 and newer, the first start shows a one-time command to run in a terminal before DazedTL can open.
- macOS has a **START.command** launcher, but it hasn't been tested yet.
- If something goes wrong, click **Copy diagnostics** in the sidebar and include it when you report the problem.

Working on DazedTL itself? See the [development guide](docs/development.md).
