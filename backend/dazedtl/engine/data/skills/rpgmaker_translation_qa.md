# RPG Maker text QA

<!-- qa-contract:rpgmaker-qa-v11
single-policy role-briefs app-owned-inventory immutable-review-bundles
scene-affine-screen lint-group-review declined-disposition evidence-preserving-deep
family-sweep decision-log consistency-check editorial-stage regression-simulation
app-publication-apply checkpoint-commit no-provider-api
-->

This one policy governs text QA: the task README and the copied handoff are made from it. DazedTL
owns the pipeline; the AI helper is the reviewer, and the local tools do the mechanical and
orchestration work. Do not create another manifest, index, checkpoint, registry or script, and
do not call a model-provider API.

## Policy

- Quality and coverage come first, then cost, then speed.
- Run QA from preparation to applied corrections without the user. Ask only when a playtest or
  context question blocks a correction and no source evidence settles it.
- Review every item you are given. If you will not review an item, decline it with a one-line
  reason that does not repeat game text; never skip, soften or shorten it. Nothing is classified
  or excluded in advance: declining is the only way an item goes unreviewed, and DazedTL offers
  it to another reviewer before reporting it as not reviewed.
- Treat stylistic preference as clean. Change a line only for a concrete defect, with the
  smallest natural correction that resolves it; equally faithful and fluent alternatives stay as
  they are. Extra slang, jokes, hostility or explanation are not repairs, and deliberate
  stiffness, restraint and awkwardness in the source stay.
- The current source, the scene and the game's glossary are authoritative. Reference-game
  translations are advisory: a difference is a reason to compare referent, function, tone and
  context, not a defect by itself.
- Preserve every runtime control code, speaker, honorific policy and line structure. For MV/MZ
  Show Text (code 401), keep `\ac` centering on every nonempty line; `\ac` directly before a
  letter hides that word (`\acWhat` hides "What"), so the fix is `\ac What`, never removing the
  code. A following control such as `\ac\C[...]` already delimits it.
- Never write game files, `findings.json` or another worker's results. DazedTL validates every
  result, simulates the apply, and applies findings through its own reviewed text batch, which
  History can restore.

## Coordinator

You run the task. Read `context.json` once for the glossary, translation guidance and reference
translations, then run `{{CLI}} status --task {{TASK}}`.

1. Use two to four reviewers when the helper can run parallel workers, each with a unique name.
   Give each the brief for its role: `{{CLI}} brief --task {{TASK}} --role <screen|deep|group|editorial>`.
   One worker may take every role in turn, except that an editorial bundle never goes to a
   worker that wrote one of its judgment corrections.
2. Workers claim bundles with `next` and submit results with `accept` until `next` returns no
   bundle; `next` moves QA through its stages by itself. Write results only in `{{RECEIPTS}}`,
   one file per bundle named after its ID; DazedTL keeps the accepted copy. A worker that cannot
   finish a bundle releases it. A worker not seen for twenty minutes, or three times a typical
   bundle's time, loses its bundle to the next idle worker; the first accepted result counts.
   `status` gives the engine's estimate of the time left.
3. Declined items move to a bundle of their own. Offer each to another worker, which claims it
   with `next --bundle <id>`; a second decline sets it aside. If no other worker is available,
   continue with `--skip-declined`. Set-aside items are reported as not reviewed; never ask the
   user to review them.
4. Deep bundles open while screening continues, and `next` hands them out once no screen
   bundle is waiting. QA then moves through the sweep and editorial stages until `status`
   reports `complete`. `{{CLI}} advance --task {{TASK}}` and `{{CLI}} finalize --task {{TASK}}`
   take the same steps by hand, which `--skip-declined` needs.
5. Record a choice every reviewer must follow, such as narration tense or a quoted label, with
   `{{CLI}} decide --task {{TASK}} --worker <name> --key <topic> --choice <choice>`; add
   `--source <Japanese> --translation <English>` when every correction of that text must use
   that wording. Reviewers read them with `{{CLI}} decisions --task {{TASK}}`.
6. When `status` reports `complete`, apply with the project helper's `qa --apply --wait 60`
   from your handoff. It applies every finding, and each question's proposal the user chose, as
   one reviewed text batch and saves a checkpoint commit. Open playtest or context questions
   wait for the user, who answers them in DazedTL's Text QA task; apply follows once every one
   has an answer, so tell the user once and keep waiting. `qa --undo <finding>` puts back one
   applied correction. Report a failed safeguard instead of working around it.

## Screen reviewer

Inspect every target in your bundle and report only exceptions; one accepted result covers the
clean targets.

- A `scene` item is one complete command-list scene in order. Lines with an `id` are your
  targets; lines with a `context_id` were targeted in another scene, but report a problem this
  scene exposes on them too. Read every line so speaker continuity, callbacks, pronouns and comic
  timing stay visible. A `cluster` item is isolated non-dialogue text.
- For every target verify who acts and to whom; pronouns, possessives and relationships;
  negation, conditions, certainty and obligation; quantities and chronology; omitted or invented
  information; and speaker voice and natural English. `context_expansion` marks a repeated
  pronoun-bearing translation assigned in more than one scene: judge it against this scene.
- Read the English exchange in order for reply continuity, rhythm, emotional beats and distinct
  voices. Treat Japanese discourse markers, stance particles, hedges and intensifiers as part of
  the whole utterance, and flag semantic inflation: a reaction to the current remark turned into
  unsupported skill, habit, frequency, progress or change over time.
- `risk` values are attention hints, not defects. Compare `same_source_alternatives` for genuine
  inconsistency and `reference_translations` for established wording.
- A line's `lint` already proposes its mechanical fixes; do not report those again.
- A `motif-family` item gathers every translation of one recurring joke or wordplay rule from
  the translation quirks. Review it once: name one recognizable English joke mechanism and check
  that every nonliteral variant still reads as its callback before calling it `preserved`;
  otherwise name the affected variants in `suspect_ids`. Sharing a name is not a callback.
- An exception's verdict is `suspect` or `needs-context`, with categories and a short concrete
  note.

## Deep reviewer

Each item states the `deep_reasons` that escalated it. Return exactly one review per item. A
deep bundle prints each scene once after its items, marking the lines each item's screen
evidence names, and lists at most twelve of an item's occurrences. Deep bundles open while
screening continues; an item whose screen evidence grew after its deep review comes back with
that `prior_review`, and your review replaces it.

- `screen_evidence` keeps the screening reviewer's reason and `screen_scene_contexts` every scene
  used to reach it. A `clean` review of such an item rebuts that reason concretely in its
  `evidence`; do not clear it because the problem is absent from the small `nearby_commands`
  window. Use `{{CLI}} context --task {{TASK}} --at <identity>` for more surrounding text.
- `motif_contexts` holds the family-level wordplay review; reconcile scene and family evidence.
  `motif-scene-contradiction` means a scene reviewer disputed a variant of a family called
  preserved, so every variant was reopened. Set `motif_ids` only when your correction or
  question concerns that joke mechanism.
- `actionable` is for a concrete, source-supported defect with a correction: severity
  `critical`, `high` or `medium`, and one category from {{CATEGORIES}}. A correction must pass
  apply's regression: DazedTL refuses one that adds a flag, changes a number, breaks a line
  structure or needs more rows than the window shows. An English ordinal ("First Stratum") may
  stand for a source number.
- Actionable `fluency`, `voice` and `wordplay` reviews carry `editorial_basis`: the concrete
  reader-facing defect, the source, scene or guidance that makes it defective, and
  `not_preference: true`.
- Set `family_key` when lines share one underlying problem, such as `term:黄泉の巌`. When the
  problem recurs word for word, add a `sweep` rule that reproduces your correction exactly;
  DazedTL then finds every other line it changes for group review.
- `apply_identities` may limit a context-specific correction to some of the item's identities.
- `uncertain-playtest` is for runtime or context uncertainty no evidence settles; say what must
  be checked in `evidence`, and give a `correction` when you have a proposal the user may choose
  instead of the current text. These become the questions the user answers in DazedTL.
- A slip in the Japanese source itself gets a `source_fix`: a Show Text header showing the wrong
  speaker's face or name, or a database text stating a number its own entry contradicts.
- A deep item's `lint` names mechanical fixes already accepted for the line; DazedTL applies
  them to your correction too, so write it for meaning and voice.

## Group reviewer

A `lint-family` item lists one mechanical family's exact fixes, and a `sweep-family` item lists
every other line an accepted correction's sweep rule changes, beside that correction. Check them
as a group and reject only the proposals that would harm their line, such as a sentence start,
a system label or a style this game deliberately keeps, with a note. Every proposal you do not
reject becomes a finding.

## Editorial reviewer

This is the last pass before corrections are applied. For each finding compare the source,
current text, correction, evidence and nearby game text, and confirm publication-ready meaning,
natural English, speaker voice, terminology and honorific policy, runtime controls, line breaks
and fit. `accept` a correction that fixes a concrete defect, `revise` it with a smaller or more
natural `replacement` for the same defect, and `withdraw` it when the current and proposed
wordings are equally valid. For `fluency`, `voice` and `wordplay`, confirm the `editorial_basis`
independently. An item's `conflicts` name corrections that contradict each other, the
translation quirks, a recorded decision or a structured label: revise until they agree, or
accept with a note when the contexts need the difference. A Show Text header fix is accepted or
withdrawn, never revised.

## Commands

Prefix every command with `{{CLI}}`:

- `status --task {{TASK}}`, `brief --task {{TASK}} --role <role>`
- `next --task {{TASK}} --worker <name> [--bundle <id>]`, then read the bundle with
  `show --task {{TASK}} --bundle <id>`, which prints it compactly; the bundle file it names
  holds the same content as JSON
- `accept --task {{TASK}} --result <result.json>`, `release --task {{TASK}} --bundle <id>`
- `advance --task {{TASK}}` and `finalize --task {{TASK}}`, each with `--skip-declined` when no
  other reviewer will take a declined bundle
- `context --task {{TASK}} --at <identity or command list>` for read-only surrounding text;
  scenes a reviewer declined are left out
- `decide --task {{TASK}} ...` and `decisions --task {{TASK}}`
- `rebuild-deep --task <earlier task>` when DazedTL reports that its QA rules changed after an
  earlier task's screen was complete: it reuses that screen's checked results in a new task

## Result formats

Every result names its `bundle_id` and the `bundle_sha256` that `next` returned. A declined item
is `{"id": "<item id>", "reason": "<one line, no game text>"}` in a screen, group or editorial
result's `declined` list, and a deep review with `"disposition": "declined"` and a `reason`.

Screen:

```json
{"schema":"{{SCREEN_SCHEMA}}","bundle_id":"screen-0001","bundle_sha256":"...","reviewed_all":true,"exceptions":[{"id":"scene-target-...","verdict":"suspect","categories":["meaning"],"note":"short concrete reason"}],"motif_reviews":[{"id":"motif-...","disposition":"preserved","note":"The joke mechanism and why every variant keeps it.","suspect_ids":[]}],"lint_reviews":[{"id":"lint-family-...","rejected":[],"note":""}],"declined":[]}
```

Deep:

```json
{"schema":"{{DEEP_SCHEMA}}","bundle_id":"deep-0001","bundle_sha256":"...","reviews":[{"id":"...","disposition":"actionable","severity":"medium","category":"voice","family_key":"term:...","motif_ids":[],"evidence":"concrete reason","correction":"Corrected text.","apply_identities":[],"editorial_basis":{"defect":"...","source_support":"...","not_preference":true},"sweep":{"find":"exact current text","replace":"exact corrected text","source_has":"optional Japanese"}}]}
```

A clean review keeps `severity` null, `category` and `family_key` empty and `correction` null.
Source fixes are `"source_fix":{"kind":"show-text","face_name":"<a face the game shows>","face_index":0,"name":"<nameplate, empty for narration>"}`
with category `speaker`, `correction` null and exactly one `apply_identities` entry, or
`"source_fix":{"kind":"database-numbers"}` on a correction that changes a number only to one of
its locator's `database_values`.

Group (lint items go in the screen result's `lint_reviews`):

```json
{"schema":"{{SWEEP_SCHEMA}}","bundle_id":"sweep-0001","bundle_sha256":"...","reviews":[{"id":"sweep-family-...","rejected":[],"note":""}],"declined":[]}
```

Editorial:

```json
{"schema":"{{EDITORIAL_SCHEMA}}","bundle_id":"editorial-0001","bundle_sha256":"...","reviews":[{"id":"QA-0001","verdict":"accept","note":""},{"id":"QA-0002","verdict":"revise","replacement":"Publication-ready wording.","note":"why"},{"id":"QA-0003","verdict":"withdraw","note":"why"}],"declined":[]}
```

## Handoff

Run DazedTL text QA for {{GAME}} from start to finish. You are the coordinator: read the task
README, {{README}}, and follow it; it holds the whole policy and every role's brief.

Apply finished findings with `{{HELPER}} --apply --wait 60`, which applies them through DazedTL
as one reviewed text batch that History can restore and then saves a checkpoint commit;
`{{HELPER}}` alone says where QA stands. The user answers open playtest or context questions in
DazedTL, and apply waits for those answers. Never edit game files yourself.

<!-- qa-focus:database -->
Database focus: the inventory holds the game's database files; review only this task's bundles.
<!-- /qa-focus:database -->

<!-- qa-focus:risky-codes -->
Risky event-code focus: the inventory holds translation-sensitive event commands; review only
this task's bundles.
<!-- /qa-focus:risky-codes -->

<!-- qa-focus:dialogue -->
Dialogue focus: review each scene as one ordered conversation, plus the motif families for
recurring humor and wordplay.
<!-- /qa-focus:dialogue -->

<!-- qa-focus:release -->
Full release focus: the inventory holds every translated line, and the task is complete only
when every bundle of every stage is accepted or reported as not reviewed.
<!-- /qa-focus:release -->
