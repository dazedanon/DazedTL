# Text QA redesign

This is the plan for the next version of text QA; implemented parts move to [architecture](architecture.md#workflow-and-shared-presentation) and leave this plan.
Current behavior lives in the [QA skill](../backend/dazedtl/engine/data/skills/rpgmaker_translation_qa.md), the [engine](../backend/dazedtl/engine/util/rpgmaker_qa.py), the [copied handoff](../backend/dazedtl/compatibility/text.py) and the [Text QA page](../app/src/features/guided/workspace/tasks/check.tsx).

## Goals

- Quality and coverage come first, then cost, then speed.
- The assistant runs QA from preparation to applied corrections, and the app shows its progress.
- The user acts only when a decision blocks QA and no evidence settles it, or when an action is consequential, such as pushing.

## Decisions

- Release QA applies independently verified findings automatically through the app's publication flow, so History can restore them.
  The findings list becomes an audit log with per-finding undo instead of a checklist before apply.
- Content handling starts only when a reviewer declines an item; QA never classifies or excludes content in advance, because which models decline what is not known beforehand.
  A declined item is offered to another reviewer, and if none will review it, finalize reports it as a coverage gap and never asks the user to attest a review; an optional queue lets the user review it.
- After apply, QA records a [checkpoint](translation-contract.md#delivery-and-future-versions) commit; pushing and publishing stay user-approved.

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

## User experience

- Starting: in Assistant-led projects QA is a phase of the method, so the starting prompt runs it with no separate handoff.
  In Guided projects the Text QA page has one primary action that prepares the task and copies it in a single click; after that the user needs to do nothing else.
- Running: one stage strip (Preflight, Lint, Screen, Deep, Consistency, Editorial, Apply) marks the current stage, and one activity line gives its count and estimate, such as "Deep review 412 of 621 · about 25 min left".
  The engine's checkpoint feeds the page and the assistant task list, so both stay current without assistant reports.
  Bundle IDs, worker names and receipts belong in Report details, not the page.
- Needs you: a card appears only when QA cannot continue without the user: an unresolved playtest or context question, a failed safeguard, or a consequential action such as pushing.
  It states the decision plainly, shows its evidence (source, current text, proposal) and offers the choices as buttons; choosing resumes QA without another copy.
- Declined items never raise a card; the coverage line reports them once, such as "9,857 lines checked · 15 not reviewed (declined by the reviewer)", with an optional link to review them.
- Done: one summary line gives the applied count and coverage, followed by the audit log grouped by category or family, with before and after, the reason and Undo for each finding; undoing everything uses History.
  There are no checkboxes before apply.
- Outdated: when the game text changed after QA, one line says so and offers Run QA again.
- Errors appear next to the control in plain language with the recovery action; an apply that failed and rolled back says so and offers the fix or a retry.
- When QA finishes or needs the user, the app notifies them through its existing notification mechanism, if it has one.
- The page follows the [UX principles](architecture.md#ux-principles) and [shared presentation](architecture.md#workflow-and-shared-presentation) rules: a compact layout, each status shown once, no zero counters or finished progress bars, and shared primitives.

## Engine

### Speed

- The engine assigns, releases and times workers, so a stalled worker is reassigned and the estimate comes from the engine.

## App and helper

- `project.py qa` also exposes undo and the Needs you choices, so a choice resumes QA.
- The QA phase of the progress report takes its stage and counts from the engine checkpoint.
- The Text QA page and the starting flow implement the [user experience](#user-experience) above.

## Order of work

1. Quality and coverage: done, described in [architecture](architecture.md#workflow-and-shared-presentation).
2. Cost: done, described in [architecture](architecture.md#workflow-and-shared-presentation).
3. Speed and presentation: engine-managed workers, the stage strip, the Needs you card and undo.
