# Text QA redesign

This was the plan for the text QA redesign; every part is implemented and described in [architecture](architecture.md#workflow-and-shared-presentation), and its goals, decisions and the evidence behind them remain here as rationale.
Current behavior lives in the [QA skill](../backend/dazedtl/engine/data/skills/rpgmaker_translation_qa.md), the [engine](../backend/dazedtl/engine/util/qa/__init__.py), the [copied handoff](../backend/dazedtl/compatibility/text.py) and [the task's view](../app/src/features/guided/TextQa.tsx).
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
- Reviewers run as four workers at once, each a fresh session for a few bundles at a time under a worker brief DazedTL writes; the coordinator starts them and reviews nothing itself.
  A [single session](#parallel-workers) taking turns under two worker names was five times slower, read more per bundle and made every check its own second read.
- A worker reads only what its bundles need: its brief carries the game's notes, quirks and decisions, each bundle the glossary entries its text uses, and claiming and accepting print the next bundle, so a bundle costs about two turns.
  Every turn rereads the assistant's whole conversation, its own long prompt included, so turns and context, not the text under review, were most of what QA [read](#token-cost).
- QA reviews a line once: a later task reads text an earlier task reviewed and left standing only as context, until its Japanese, its English or the glossary entries and quirks governing it change, and the user can name a version whose earlier text was checked before DazedTL.
  Scoping QA by declining lines, as coordinators did for an update, cost a full inventory each time and made screen checks count the declined lines as misses.

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

### Parallel workers

The release QA of Fuuma Chronicle: Tower of Lilith ran for more than twelve hours, with one session doing all the reviewing:

- The policy let one worker take every role in turn, so the coordinator started no workers.
  It reviewed every bundle itself, taking turns under two worker names because a check must go to another worker than the one that screened its lines, so each check was the same session reading its own lines again.
- It screened 352 bundles, half of them checks, in 9.5 hours, about 37 an hour, and its conversation was compacted about once an hour.
- An earlier attempt at the same task, whose coordinator ran four sub-agents in runs of six to eight bundles, reviewed 87 bundles in 28 minutes, about 190 an hour.
  It read about 1.0 million cached tokens per bundle to the single session's 2.6 million, since a short run keeps its conversation small; the two ran on different models, so that comparison is approximate.
- That coordinator wrote its own worker guide, which also told the workers what to decline, a choice the policy leaves to each reviewer.
  A worker brief DazedTL writes gives every coordinator the same loop and leaves nothing to add but decisions every reviewer follows.
- The time left divided the work by the worker names seen in the last half hour, so the session taking turns under two names showed half its real time left.

### Token cost

The release QA of HOLLOWWALD's 1.10 update, run by four Sonnet 5.5 workers, took three hours and about $128 at API prices; the workers' transcripts show where the tokens went:

- A worker took four to six turns a bundle, and every turn reread its whole conversation, whose fixed part, the assistant's own prompt, was about 50,000 tokens.
  That prompt was 41% of what workers read, and the text under review 17%.
- Workers read the 82 KB task context in pieces (9%), game and task files (7.5%) and their brief (7%), so looking things up cost more than the text they reviewed.
- The user wanted only the update's text reviewed, so the coordinator declined about 3,400 screen items in each of the seven tasks prepared in eight hours.
  Checkers told to leave older lines alone counted as missing what the first screen had flagged, so every reviewer was checked in full: a quarter of all tokens, for 19 more exceptions.
- Prepared on the three earlier tasks' reviews and the text from before 1.10, the same game screens 1,312 targets in 76 bundles instead of 20,191 in 206, and prints 2.0 of 6.65 million characters.

Four of its maps, about 450 lines with 20 seeded defects of meaning, negation, names, pronouns, numbers, terminology, voice and an omission, were reviewed by four Sonnet workers under each version of the engine:

- Before the change, the workers corrected all 20 and 11 other lines, in 225 turns that read 23.4 million tokens, $7.86 at API prices, in 16 minutes.
- With bundles printed by `next` and `accept --next`, glossary entries in the bundle and guidance in the brief, they corrected all 20 and 10 other lines in 160 turns, 16.9 million tokens and $6.45, in 15 minutes.
  They still redirected `next` to files and read them back, opened the engine's code to learn result formats and searched the task's files.
- With a brief that says every turn rereads the conversation and forbids those lookups, they corrected all 20 and 18 other lines, most of them glossary terms the bundle's notes showed, in 90 turns, 8.4 million tokens and $4.66, in 10 minutes.

## Release playtest

Text QA reads text; it cannot tell whether the game starts, which text reaches the screen or whether it fits there.
The release playtest is the last check before Release: it plays the game as DazedTL applied it, with its translations, QA corrections, rewraps and plugin files, and reports what a player would hit.
Its behavior is in [architecture](architecture.md#workflow-and-shared-presentation); its goals are text QA's, and these are its decisions and the evidence behind them.

### Where it sits

- In Guided it is part of Text QA's copied task for MV/MZ games: the assistant plays the game while QA's workers review, fixes what it finds, and plays it again after QA's apply; Release never waits for it.
  Inside the task, its findings in translated text join a review in progress, while a separate task after QA would need QA to run again; and the user hands over the whole final check once.
  Text problems the play after QA's apply finds need QA's next round, which the assistant prepares and reviews itself, so the user still copies once; the task is finished only once a play of the game as it is leaves nothing for QA.
  A game the playtest can't play at all, such as one without its engine's scripts, finishes the task without a play once its report names no crash, since nothing the assistant writes would change it; a crash that stops the game is the assistant's to fix, so the task waits on it rather than reading Blocked.
- In Assistant-led the starting prompt runs it through the project helper's `playtest` before text QA and again after QA's apply, and a Playtest tab shows its report once one exists.
  Its assistant fixes the game's own code through the same fixes plugin and play as Guided's, never by editing the game's files, and DazedTL then saves the fixes in a checkpoint, since Assistant-led has no History restore and its Git history is how it takes changes out.

### Decisions

- Every run checks the game's files and then plays it, with no one at the keyboard, started by the assistant through the helper; the Assistant-led tab can run it again.
  The checks are static and the same for MV and MZ; the tour runs in a hidden window of DazedTL's own Electron, so it works the same on every system and never starts the game's executable.
- The playtest never writes the game: no saves, settings or fixes go into the game folder.
- Problems are fixed where their own reviewed path already applies verified fixes, never by the playtest.
  Problems in lines text QA reviews become [observations](#observations) of a `playtest` worker, both when QA is prepared and while it reviews, so a deep reviewer corrects them and editorial confirms the correction before QA applies it by itself.
  Plugin text goes to Plugin files, text never translated to Translate, and crashes and window sizes to a fixes plugin of DazedTL's own, which the assistant writes.
  The playtest's checks find where a problem is, not the wording or code that fixes it.
- Fixes for the game's own code go in only after the playtest plays the game with them in place, as fit checks confirm on screen: the play must still play, stop nowhere new, reach as many places and no longer show something the last playtest found.
  They live in one plugin that `js/main.js` loads after the game's plugins, so the game's plugin files and plugin list stay as Plugin files applied them, one file says what changed, and Guided's History takes them out like any applied batch.
- Running it again is how kinks are ironed out, so every run is idempotent: QA prepared again with the same text is the same task whatever the playtest found, a task records each finding once per reason, and each report counts what was fixed since the last one and marks what is new.
- Only what the tour drew on screen counts as seen; a static reach or line count says where to look, because fonts, plugins and custom windows decide what fits and what shows.
  On 2026-10-19 descriptions still went to QA by line count alone: Slime Hunter Nena's engine gives its help window three lines, and Arina's gear help draws a description's first sentence beside a stats line of its own, so 23 descriptions reached review as cut off when none was.
  A description now counts once the tour sees its own text run past the bottom of its window, and text a plugin draws beside it, such as that stats line, is the game's to fix.
- What the tour cannot reach is a coverage gap in the report, never a request for the user to play it or confirm a review.
  The assistant adds stops for what only it can find, such as a dungeon floor with a trap or the recollection room, and the app keeps them for every later run.
- Text a plugin draws on screen is player text, so Plugin files decides again about such text it kept in Japanese; a screen the tour opened on its own may be one players never reach, as Arina's trial-end screen showed, so the evidence says so.
  Strings in plugin code Plugin files kept in Japanese, such as notetag and comment keys, count only once drawn: on 2026-10-20 Fuuma Chronicle's playtest listed 20 plugins of them by code reach alone, which reopened a Plugin files run that found nothing visible.
- A screen the tour opens on its own, without what the game sets up first, an error a plugin raises because it needs NW.js, and a stop that fails, such as one starting an event whose page the game has not turned on, are coverage gaps rather than crashes, because none says anything about the game players run.

### Why the playtest

On 2026-10-11 a manual QA of Arina and the Succubus Curse, after text QA, found what text QA could not:

- Help windows sized for the Japanese clipped English descriptions: a plugin's skill screen with a help window one line high, and a three-line item description in a two-line help window.
- State and skill messages without the battler's name, because the Japanese started with は or の and had no `%1` either.
- Japanese string literals left in partly translated plugins; most could not show, behind disabled flags, in functions nothing called or in unused data such as a synopsis file, so reach matters.
  Hooking `drawText` told text that shows from dead code more reliably than reading the code.
- A Japanese placeholder glyph, `◯`, in English interface text.

On the same game before those fixes, the playtest found every one of them, the dungeon plugin's trap text once a stop triggered a trap, and two armor descriptions the manual QA had missed, clipped in the item screen.
It reached eight of its nine stops in about 90 seconds; the ninth stopped at a custom menu framework's base screen, which the game never opens on its own.

The manual run also showed what a harness must avoid:

- MZ pauses while the page lacks focus, so the tour overrides `SceneManager.isGameActive`.
- Setting `Input._currentState` directly is unreliable; real `keydown` and `keyup` events are not.
- Loading a save over an active map makes a plugin read a map that is gone and report a crash the game does not have, so the tour loads through `Scene_Load`.
- A hidden browser pane stops animation frames; DazedTL's offscreen window keeps them running.

Building the tour added more:

- A window drawn while hidden, or a message's page break, looks like overflow, so a finding counts only once its bitmap is on screen, and message windows go on in a new page.
- A window may size its contents to its glyphs rather than its lines, as Keke_PredictionSystem's action view does, and MZ flushes an empty line after a closing line break, so text counts as past a window's bottom only where the glyphs it drew reach past it.
  On 2026-10-20 that empty line made Fuuma Chronicle's battle action labels look cut off, and the assistant spent two fix rounds on them.
- An opening left mid-message holds the next stops' screens, so the tour plays it until the player can move, four times as fast.
- A battle the tour starts on a map with no background loads the engine's default, which a game may not ship, so it shows the game's own or none.
- Chromium's headless platform gives an offscreen window a single pixel unless it has a screen size, and reaches the GPU without a display only through EGL; a game that still never starts, as on a machine without a GPU, plays with SwiftShader.
