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
- Reviewers run as four workers at once, each a fresh session for a few bundles at a time under a worker brief DazedTL writes; the coordinator starts them and reviews nothing itself.
  A [single session](#parallel-workers) taking turns under two worker names was five times slower, read more per bundle and made every check its own second read.

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

## Release playtest

Text QA reads text; it cannot tell whether the game starts, which text reaches the screen or whether it fits there.
The release playtest is the last check before Release: it plays the game as DazedTL applied it, with its translations, QA corrections, rewraps and plugin files, and reports what a player would hit.
Its behavior is in [architecture](architecture.md#workflow-and-shared-presentation); its goals are text QA's, and these are its decisions and the evidence behind them.

### Where it sits

- In Guided it is the third optional Check task, Playtest, after Line width check and Text QA, because it checks the text those tasks leave; Release never waits for it.
- In Assistant-led the starting prompt runs it through the project helper's `playtest` before text QA and again after QA's apply, and a Playtest tab shows its report once one exists.

### Decisions

- Every run checks the game's files and then plays it, with no one at the keyboard: one click in Guided, or the assistant through the helper.
  The checks are static and the same for MV and MZ; the tour runs in a hidden window of DazedTL's own Electron, so it works the same on every system and never starts the game's executable.
- The playtest never writes the game: no saves, settings or fixes go into the game folder.
- Problems are fixed where their own reviewed path already applies verified fixes, never by the playtest.
  Problems in lines text QA reviews become [observations](#observations) of a `playtest` worker, both when QA is prepared and while it reviews, so a deep reviewer corrects them and editorial confirms the correction before QA applies it by itself.
  Plugin text goes to Plugin files, text never translated to Translate, and crashes and window sizes to the game's own code, which the assistant changes.
  The playtest's checks find where a problem is, not the wording or code that fixes it.
- Running it again is how kinks are ironed out, so every run is idempotent: QA prepared with the same findings is the same task, a running task records each finding once, and each report counts what was fixed since the last one and marks what is new.
- Only what the tour drew on screen counts as seen; a static reach or line count says where to look, because fonts, plugins and custom windows decide what fits and what shows.
- What the tour cannot reach is a coverage gap in the report, never a request for the user to play it or confirm a review.
  The assistant adds stops for what only it can find, such as a dungeon floor with a trap or the recollection room.
- A screen the tour opens on its own, without what the game sets up first, and an error a plugin raises because it needs NW.js, are coverage gaps rather than crashes, because neither says anything about the game players run.

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
- An opening left mid-message holds the next stops' screens, so the tour plays it until the player can move, four times as fast.
- A battle the tour starts on a map with no background loads the engine's default, which a game may not ship, so it shows the game's own or none.
- Chromium's headless platform gives an offscreen window a single pixel unless it has a screen size, and reaches the GPU without a display only through EGL; a game that still never starts, as on a machine without a GPU, plays with SwiftShader.
