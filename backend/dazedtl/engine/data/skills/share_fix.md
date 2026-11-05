Help me share a fix with DazedTL's developers.
In this chat, or in this game folder, we fixed something DazedTL got wrong in my game.
Write a short report a DazedTL developer can act on, so DazedTL can handle games like this one by itself.

<sources>
- Start from what we did in this chat.
- The game folder is a Git repository, and DazedTL saves each change as a checkpoint commit: `git log`, `git show`, `git status` and `git diff` show what changed, including edits not committed yet.
- `AGENTS.md` at the game folder's root, when it exists, holds the assistant notes: what anyone working on this game must know. Read it first.
- DazedTL keeps its work for the game in `.dazedtl/`: `settings.json`, `glossary.txt`, the game context and style in `skills/`, and Guided's saved findings in `guided/`.
- Only read: change nothing while you write the report.
</sources>

<report>
Write it in Discord Markdown, under 1,900 characters so it fits one Discord message, with these parts in this order:

{facts}

**Problem:** what I saw go wrong, in one or two sentences, such as "Speaker names in a plugin's name codes weren't detected."
**What we changed:** each change and where it is. Name DazedTL's settings as DazedTL shows them, such as plugin parameters, speaker formats, custom patterns, the glossary or a setting. Name game files edited by hand by their path inside the game folder. Give a small before and after excerpt of each, a few lines at most.
**How we tested it:** the scene or map we checked in the game, and what we saw there.
**Could DazedTL do this itself?** Say whether the fix is specific to this game or a pattern other games share, such as the same plugin, engine feature or text format. Then say how DazedTL could handle it automatically. For example: name codes and variables must never be translated, but DazedTL should still detect them as a speaker format for Batch requests.
</report>

<rules>
- If the Game line above is blank, fill it in from the game folder: the game's title and engine. Leave out a blank Mode line.
- Leave out API keys, tokens, passwords and the value of any setting that holds one, even in excerpts.
- Leave out long stretches of game text: quote only the few lines that show the pattern.
- Write paths inside the game folder only, never my home folder or user name.
- Reply with the report alone, so I can paste it into Discord as it is.
</rules>
