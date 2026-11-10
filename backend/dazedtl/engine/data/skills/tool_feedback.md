This translation with DazedTL is finished, as far as you take it.
Its last step is tool feedback: a short note for DazedTL's developers on what DazedTL itself could do better, from what you met in this translation.
The user posts it in DazedTL's Discord, where other users read it too, so it holds nothing private.

<cover>
- What DazedTL made harder than it needed to be: its steps and their order, the prompts and task files it gave you, its checks (refusals, false alarms, problems they missed), errors and failures you met, and engine features or file formats it could not read or write.
- For each problem: the phase it happened in, as DazedTL names it (Set up, Context, Translate, Check or Release in Guided steps; preparation, extraction, translation, images, injection, qa or patch in Assistant-led), the engine, what happened, and what would have helped.
- The problems that cost the most time, tokens or quality first. Leave out problems of the game itself that no tool could solve, and slips of your own that DazedTL could not have prevented.
- Count problems met earlier in this translation too: read what the game's assistant notes and your status notes say went wrong, when they exist.
- When nothing went wrong, say so in How it went and write None in the other parts.
</cover>

<never>
- Game text beyond a few words: name the file, map, event or plugin instead of quoting its lines.
- Your home folder or user name: write paths inside the game folder relative to it, and DazedTL's own files by their name, such as `rpgmaker_translation_qa.md`.
- API keys, tokens, passwords, run or request IDs, hashes, account names, e-mail addresses and anything else secret or meaningful only on this computer.
- DazedTL's version, your system, the game's name and the method: DazedTL adds them when the user copies the feedback.
</never>

<format>
Discord Markdown, at most {{LIMIT}} characters, with these parts in this order and nothing before or after them:

**How it went:** one or two sentences: how far the translation got and how smoothly DazedTL's steps went.
**Problems:**
- Phase (engine): what happened, and what would have helped. At most six, or None.
**Missing engine support:** what this engine or its formats needed that DazedTL lacks, or None.
**Ideas:**
- An improvement to DazedTL you suggest. At most three, or None.
</format>

<save>
Write the feedback in UTF-8 to `{{DRAFT}}` in the game folder and run `{{SAVE}}`.
DazedTL checks it, saves it where the user's DazedTL shows it, and removes the draft; when it refuses the text, it says what to change, so change that and run it again.
Feedback saved earlier in this translation is replaced: when `{{SHOW}}` prints saved feedback, keep its points that still hold.
Then end your report to the user with one line saying the tool feedback is saved, and stop.
</save>
