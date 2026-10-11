# Text QA redesign

This was the plan for the text QA redesign; every part is implemented and described in [architecture](architecture.md#workflow-and-shared-presentation), and its goals, decisions and the evidence behind them remain here as rationale.
Current behavior lives in the [QA skill](../backend/dazedtl/engine/data/skills/rpgmaker_translation_qa.md), the [engine](../backend/dazedtl/engine/util/rpgmaker_qa.py), the [copied handoff](../backend/dazedtl/compatibility/text.py) and [the task's view](../app/src/features/guided/TextQa.tsx).
The [release playtest](#release-playtest) extends the same goals to what text QA cannot see: whether the game starts, what reaches the screen and whether it fits.

## Goals

- Quality and coverage come first, then cost, then speed.
- The assistant runs QA from preparation to applied corrections, and the app shows its progress.
- The user acts only when a decision blocks QA and no evidence settles it, or when an action is consequential, such as pushing.

## Decisions

- Release QA applies independently verified findings automatically through the app's publication flow, so History can restore them.
  The findings list becomes an audit log with per-finding undo instead of a checklist before apply.
- Content handling starts only when a reviewer declines an item; QA never classifies or excludes content in advance, because which models decline what is not known beforehand.
  A declined item is offered only to a reviewer on another AI helper, because a helper's workers share its boundaries and offering it to another of them would ask the same helper again.
  If none will review it, finalize reports it as a coverage gap and never asks the user to attest a review; an optional queue lets the user review it.
- After apply, QA records a [checkpoint](translation-contract.md#delivery-and-future-versions) commit; pushing and publishing stay user-approved.
- Screening is measured instead of trusted: another reviewer screens a quarter of every reviewer's lines again, whatever either reports goes to deep review, and a reviewer whose checks show it missed more than it found is screened again in full.
  Seeded known-defect probes and per-reviewer yield tracking were rejected, for the [reasons](#screen-checks) below.
- A defect a reviewer notices outside its own items reaches the engine as an [observation](#observations), never only as prose: the engine checks the line against the inventory and sends it to deep review, in a follow-up round when deep review is over, so its correction still passes the editorial stage.
  Observations on lines in declined scenes stay out, like the lines themselves.
- A deep review can correct a scene as a unit: several of its lines, each with its own text, applied and undone together and reviewed together in editorial.
  Single-line corrections and word-for-word sweep rules cannot fix a [defect that spans a scene](#scene-corrections), and the unit keeps such a fix from being half applied, half undone or left partly in declined text.

## Why

The first complete release QA, of Arina and the Succubus Curse with 102 screen bundles and 621 deep items, showed these gaps:

- The skill, the copied handoff and the task README disagreed about applying.
  Following the handoff left no correction map, so the Text QA page had nothing to offer for choosing.
- Screen flags were precise and mechanical triggers were not: 307 of 338 deep items from screen exceptions became corrections, but only 6 of 269 forced items did.
- Per-bundle screening flags samples of a systematic problem rather than every instance: after 313 findings, a sweep of the accepted families found 250 more lines.
- When reviewers declined some scenes, nothing could skip or set aside a scene, so whole bundles of ordinary text were held with them, and accepting those bundles later recorded reviews that never happened.
- One accepted correction, "First Stratum" for 第1層, would have rolled back the entire apply, because the post-apply regression treats its new visible-number flag as blocking and no earlier stage checked it.
- Corrections, supplementary fixes and source fixes were applied from the command line, outside the publication flow, so History cannot restore them and the app still showed QA as pending.
- Decisions, declined content and the editorial pass were visible only in the assistant's chat, and the user stepped in about fifteen times.
- The run used about six million assistant tokens; deep items embedded whole scenes, so one set of deep drafts held 9.5 MB until scenes were grouped and printed once (2.3 MB).

### Screen checks

The second complete run of the same game, after the redesign, showed that one screen per bundle reports only exceptions, so a shallow pass looks like a clean bundle:

- Reviewers with comparable lists of about 1,000 targets each raised between 1 and 21 exceptions, and deep review confirmed 72 of all 78, at least 83% for every reviewer, so the high counts were real problems rather than noise.
- 8,825 distinct texts were unchanged between the runs and screened in both; the second run's screen flagged 70 that the first had passed, and deep review corrected 65 of them.
- The first run's bundles raised from 2 to 89 exceptions per 1,000 targets between the lowest and highest quarter, yet the problems the second run found stayed between 6 and 8 per 1,000 in every quarter.
  Yield tracking would reopen bundles that hide no more misses than the rest; only a second screen of the same lines measures what a screen missed, and its flags are precise enough to send straight to deep review.
- Seeded probes would put synthetic lines into immutable bundles, where the context view gives them away, and would test only the defects planted; the missed problems were echoes, voice, speakers and terminology.
- Screen bundles were 4.4 MB of the 6.4 MB reviewers read, so a quarter checked in whole bundles adds about a fifth.
  In a model of the second run's reviewers, escalation raised that to about two fifths and doubled the misses recovered; it checked the reviewer with 1 exception in full in 92% of runs and the one with 21 in none.

### Observations

The same second run showed that reviewers could report what they noticed outside their own items only in prose, to the coordinator, so none of it reached deep review.
Among others, they found a state message missing its subject like the one just corrected, a broken echo corrected on one event page but not on the next, and a wrong nameplate corrected at one command but likely repeated two commands later.

### Declines within a helper

The same second run showed that declines must stay within a helper and reach single family members:

- `next` offered the coordinator's declined scenes to its own sub-reviewers, which run on the same helper.
  To keep them away, the coordinator gave each sub-reviewer a fixed bundle list, hid the declined items from `show` and `context`, and wrote the declines into each sub-reviewer's result, so the checkpoint named sub-reviewers as the decliners.
- A lint family mixes proposals from many scenes, and a motif family variants from many scenes, but only whole items could be declined.
  Proposals from declined scenes went into `rejected` with a note that nobody read them, and a motif family was called preserved with a note that two variants were unread.

### Scene corrections

The same second run left defects that span a scene.
Map010 event 120 page 2 narrates in the past tense until the climax and in the present for its last five boxes.
Deep review could retense only the box its item named, which moved the switch one box later, so editorial withdrew that correction as no better than the text it replaced (QA-0050).
Map013 event 19 page 2 had the same shape (QA-0093).

## Release playtest

Text QA reads text; it cannot tell whether the game starts, which text reaches the screen or whether it fits there.
The release playtest is the last check before Release: it plays the game DazedTL has applied, with its translations, QA corrections, rewraps and plugin files, and reports what a player would hit.

### Where it sits

- In Guided it is the third optional Check task, Playtest, after Line width check and Text QA, because it checks the text those tasks leave; like them, Release never waits for it.
- In Assistant-led the starting prompt runs it through the project helper's `playtest` before text QA and again after QA's apply, and the app shows its report in a Playtest tab once one exists.
- Each run checks the files as they are and reports what it found; a later change to the game marks the report outdated.

### What is automated

Every run does both parts by itself; the user starts it with one click or the assistant with the helper, and nobody plays.

Static checks read the game's files in seconds, the same way for MV and MZ:

- Whether it starts: every data file parses as JSON, `js/plugins.js` holds a readable plugin list, and every enabled plugin compiles as a browser script; nothing runs.
- Japanese players can read: the fields text QA's [preflight](../backend/dazedtl/engine/util/rpgmaker_qa_preflight.py) reads, in the current text whether or not it was translated: Show Text and its nameplate, choices, scrolling text, the name-change commands, database names, descriptions and messages, and System's terms.
  Branch labels (402), file names and plugin-command identifiers are not text; `・` and `ー` are not Japanese, and a Japanese placeholder glyph such as `◯` left in English text is.
- Codes against the original, which the `_original` beside translated text keeps: each `%1` and `%2` of a battle message and System's message terms, an MZ battle message whose original starts with a particle such as は or の but lacks `%1`, and each event page's `\V[n]`, `\N[n]`, `\P[n]`, `\I[n]` and `\G`, counted per page so a code a rewrap moved to another line does not count as lost.
- Descriptions with more lines than the two the standard help window shows.
- Plugin text: every Japanese string in an enabled plugin's code, read with comments, keys, comparisons, speaker tags and asset names left out, and each given its reach: drawn directly, behind a condition that is always false, in a function nothing calls, or may show.

The runtime tour then plays the game in a hidden window of DazedTL's own Electron, at the game's resolution, from a local server that serves the game folder read-only.
It uses a fresh browser profile in the report's folder, so saves and options never reach the game, and it is muted.
Hooks installed before the title screen record:

- errors: `console.error`, uncaught errors and rejections, and the engine's own error screen;
- Japanese actually drawn, through `Bitmap.prototype.drawText`, with the scene, map, a short stack and the plugin file and line that drew it;
- text that runs past its window's contents, through `Window_Base` `processNewLine` and `flushTextState`, leaving out passes that only measure and `Window_NameBox`;
- each message and choice list, tied to its event command by the identity of the interpreter's command list, and each help text to its database entry.

The tour presses real keys and stops at the title, New Game with its opening messages and first choices, every main-menu screen and tab, a save and a load through the real save and load screens, a shop, a battle, each screen a plugin defines, and the title again.
For the menus and the shop the party holds one of every item, weapon and armor and knows its skill types' skills, so every description draws once in its real help window; this state exists only in memory and the tour's own save.
A stop that crashes the game ends with its error, and the tour reloads and goes on with the next stop.
The assistant adds stops for what only it can find, such as a dungeon floor with a trap and a chest or the recollection room: a map position, an event, a common event, a troop, a screen, or a script that uses a debug plugin such as Forge to get there.

### What the app shows

The Playtest task shows where the run stands, then each problem once, with where it was seen and a capture when the tour saw it:

- Crashes: the game stopped or a script failed, with the stop, screen, file and line.
- Japanese on screen: seen in the game, or found in the files with its reach.
- Text that doesn't fit: seen running past its window, or a description longer than its help window that no stop drew.
- Missing names and codes: a `%1`, `\V[n]` or similar the original shows and the translation dropped.

Each problem names the task that fixes it: Text QA for lines it reviews, Plugin files for plugin text, Translate for text never translated, or the game's code for crashes and window sizes, which the assistant changes.
A coverage line counts the stops the tour reached; its sheet lists what it could not reach and why, such as a plugin screen that needs the game's own runtime.

### Decisions

- The playtest never writes the game: no saves, settings or fixes go into the game folder, and it changes nothing a release ships.
- Findings on lines text QA reviews reach text QA as [observations](#observations) by a `playtest` worker, when QA is prepared and while it reviews, so a deep reviewer corrects them and editorial confirms the correction before it applies by itself.
  The playtest does not correct text, because its checks find where a problem is, not the wording that fixes it.
- Only what the tour drew counts as seen; a static reach or line count is evidence of where to look, because fonts, plugins and custom windows decide what fits and what shows.
- What the tour cannot reach is a coverage gap in the report, never a request for the user to play it or confirm a review.
- The tour runs DazedTL's Electron rather than the game's NW.js, so it works the same on every system without starting the game's executable, and nothing it does touches the user's saves.
  A plugin that needs NW.js's Node APIs fails there; its errors are coverage gaps, not crashes.
- Text QA's battler-name check also reads the particle at the start of an MZ message's source, so the source fix that adds `%1` reaches a message whose English starts with a capital.

### Why the playtest

On 2026-10-11 a manual QA of Arina and the Succubus Curse, after text QA, found what text QA could not:

- Help windows sized for the Japanese clipped English descriptions: a plugin's skill screen with a help window one line high, and a three-line item description in a two-line help window.
- State and skill messages without the battler's name, because the Japanese started with は or の and had no `%1` either.
- Japanese string literals left in partly translated plugins; most could not show, behind disabled flags, in functions nothing called or in unused data such as a synopsis file, so reach matters.
  Hooking `drawText` told text that shows from dead code more reliably than reading the code.
- A Japanese placeholder glyph, `◯`, in English interface text.

The manual run also found what a harness must avoid:

- MZ pauses while the page lacks focus, so the tour overrides `SceneManager.isGameActive`.
- Setting `Input._currentState` directly is unreliable; real `keydown` and `keyup` events are not.
- Loading a save over an active map makes a plugin read a map that is gone and report a crash the game does not have, so the tour loads through `Scene_Load`.
- A hidden browser pane stops animation frames; DazedTL's offscreen window keeps them running.
