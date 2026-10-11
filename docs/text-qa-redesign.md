# Text QA redesign

This was the plan for the text QA redesign; every part is implemented and described in [architecture](architecture.md#workflow-and-shared-presentation), and its goals, decisions and the evidence behind them remain here as rationale.
Current behavior lives in the [QA skill](../backend/dazedtl/engine/data/skills/rpgmaker_translation_qa.md), the [engine](../backend/dazedtl/engine/util/rpgmaker_qa.py), the [copied handoff](../backend/dazedtl/compatibility/text.py) and [the task's view](../app/src/features/guided/TextQa.tsx).

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
