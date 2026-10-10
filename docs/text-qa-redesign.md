# Text QA redesign

This is the plan for the next version of text QA; nothing here is implemented yet.
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
- The app generates the copied handoff from the QA skill, so one policy governs the skill, the task README and the handoff.

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

### Quality and coverage

- Preflight reports Japanese left in custom data files and plugin parameters, even when the engine cannot correct it.
- Screen and deep results accept a declined disposition for a scene or item, with the reviewer's reason.
  The engine moves a declined scene into its own bundle so the rest of its bundle can be accepted, offers it to another reviewer, and otherwise skips it in deep review and reports it in findings as a coverage gap.
  Workers can claim a bundle by ID.
- A deterministic lint stage proposes fixes for known families before screening, so screening concentrates on meaning and voice.
  The first families are spacing after ♥, stray letters for the small っ, dakuten apostrophes on real words, list items merged onto one line, quoted titles that no longer match their target, duplicated labels and level-tag spacing.
- After deep review, a family sweep turns every line matching an accepted family into a candidate finding with the family's correction, reviewed as a group.
- New finding types cover Show Text face and name fixes for source slips, and database fields.
- A decision log shared by reviewers records choices such as narration tense or a quoted label, and a consistency check reports conflicting corrections before the editorial pass.
- Finalize simulates the post-apply regression: each correction's mechanical flags and line counts are checked, so a correction that would block apply never reaches findings.
  The visible-number check treats ordinal words as numbers.

### Cost

- Forced deep review keeps only checks that find defects: number checks ignore ordinals, kanji numerals and idioms such as 1番, and runtime-token checks skip codes that survive unchanged.
- Deep bundles group items by scene, print each scene once and cap long occurrence lists.

### Speed

- Deep review starts on accepted screen bundles instead of waiting for the whole screen.
- The engine assigns, releases and times workers, so a stalled worker is reassigned and the estimate comes from the engine.

## App and helper

- `project.py qa` exposes status, report, apply, undo and the Needs you choices through the running app, so every game write goes through the publication flow and appears in History, and a choice resumes QA.
  No QA command writes game files directly.
- The QA phase of the progress report takes its stage and counts from the engine checkpoint.
- The Text QA page and the starting flow implement the [user experience](#user-experience) above.

## Skill

- One policy covers the screen, deep, editorial and apply roles, with a fixed brief for each role.
- Rendering moves into the engine: scene-grouped deep bundles, a read-only context viewer that leaves out declined scenes, and the regression simulation finalize uses.

## Order of work

1. Quality and coverage: the single policy with automatic apply through the app, the declined disposition, the lint stage and family sweep, the regression simulation in finalize, and inventory completeness.
2. Cost: the forced-review filters and scene-grouped deep bundles.
3. Speed and presentation: early deep review, engine-managed workers, the stage strip, the Needs you card and undo.
