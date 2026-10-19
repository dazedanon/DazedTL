# RPG Maker text QA

<!-- qa-contract:rpgmaker-qa-v18
single-policy role-briefs parallel-workers worker-brief app-owned-inventory immutable-review-bundles database-checks
battler-name-source-fix
scene-affine-screen sampled-screen-checks lint-group-review glossary-lint declined-disposition
helper-scoped-declines unit-declines coordinator-declines evidence-preserving-deep
scene-correction family-sweep decision-log consistency-check editorial-stage regression-simulation
app-publication-apply checkpoint-commit no-provider-api interface-captures
bundle-glossary worker-guidance accept-next
-->

This one policy governs text QA: the task README and the copied handoff are made from it. DazedTL
owns the pipeline; the AI helper is the reviewer, and the local tools do the mechanical and
orchestration work. Do not create another manifest, index, checkpoint, registry or script, and
do not call a model-provider API.

## Policy

- Quality and coverage come first, then cost, then speed.
- Run QA from preparation to applied corrections without the user. Ask only when a playtest or
  context question blocks a correction and no source evidence settles it.
- Review every item you are given.
  If you will not review an item, decline it with a one-line reason that does not repeat game text; never skip, soften or shorten it.
  Nothing is classified or excluded in advance: declining is the only way an item goes unreviewed, and DazedTL offers it to a reviewer on another AI helper before reporting it as not reviewed.
  Workers on one helper share its boundaries, so an item one of them declined never goes to another of them.
  Decline a single lint proposal, sweep candidate or motif variant by its own ID and review the rest of its family; never reject a proposal, or call a joke preserved, on lines you did not read.
- Never leave a concrete defect you notice outside your own items in prose alone, whether in
  `nearby_commands`, `context` output, another scene or after your result was accepted. Add an
  observation to that result or your next one, naming the line and a short concrete reason.
  DazedTL sends the line to deep review with your reason as its screen evidence, in a follow-up
  deep round when deep review is over, so its correction still gets the editorial pass. A line
  in a scene reviewers declined stays out.
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

You run the task; four workers review it at the same time.
Run `{{CLI}} status --task {{TASK}}`; read the task's context, {{CONTEXT}}, only when a choice you must settle needs its glossary or guidance, since each worker's brief and bundles carry what reviewing needs.

1. Start four workers that run at the same time, such as background sub-agents, each a fresh session with a name of its own, such as `rev-1` to `rev-4`.
   Give each only this prompt: `You are text QA worker <name>. Run {{CLI}} brief --task {{TASK}} --role worker and follow it.`
   A worker's run ends after a few bundles, which keeps its reviews sharp and its cost low, with one line saying how far it got; start its next run under the same name with the same prompt until `status` reports `complete`.
   Restart a worker that `next` gave no bundle once `status` shows `bundles_pending` again or no worker is running, since accepted bundles open new ones and `next` opens the next stage.
   Choices every reviewer must follow go through `decide` (step 6), never into a worker's prompt.
   Never review bundles yourself, and never give one session two worker names: a check is another reviewer's independent read, so DazedTL keeps it from the worker that screened its lines, and an editorial bundle from a worker that wrote one of its judgment corrections.
   When your helper cannot run workers at the same time, run them one after another; when it cannot start workers at all, report that instead of reviewing under several names.
   A worker runs on your helper unless it names another, such as a different AI helper or model, with `--helper <name>` on its first `next` or `decline`.
2. `next` moves QA through its stages by itself.
   A worker not seen for twenty minutes, or three times a typical bundle's time, loses its bundle to the next idle worker; the first accepted result counts.
   `status` gives the engine's estimate of the time left, and reports `one_at_a_time` when bundles waited while QA reviewed one at a time: start the workers that are missing.
3. Declined items move to a bundle of their own, which `next` offers only to workers on another helper; a decline there sets it aside.
   Decline items you read and will not review, such as a scene with its lint proposals and motif variants, with `decline` under your own name while no worker holds their bundle; the rest of the bundle then reaches your workers without them.
   When no worker on another helper will take them, give `next` `--skip-declined`, and it sets them aside once the rest of their stage is reviewed.
   Screening then goes on in follow-up bundles for set-aside lines that other scenes also show, which `next` hands out like any other.
   Set-aside items are reported as not reviewed; never ask the user to review them.
4. A check bundle, whose ID ends in `-c1`, screens another reviewer's accepted lines again.
   DazedTL checks at least a quarter of each reviewer's scene and line targets, starting with its first bundle, and every bundle of a reviewer whose checks found at least two problems it missed and more than it found there.
   What either screen reports goes to deep review, and `status` counts checks apart from coverage under `screen.checks`.
   Lines a check declines stay screened once and count as unchecked, so another bundle is checked in their place.
   Screening ends only when every check is accepted, so keep at least two workers running until then.
5. Deep bundles open while screening continues, and `next` hands them out once no screen bundle is waiting.
   QA then moves through the sweep and editorial stages until `status` reports `complete`.
   `{{CLI}} advance --task {{TASK}}` and `{{CLI}} finalize --task {{TASK}}` take the same steps by hand.
6. Record a choice every reviewer must follow, such as narration tense or a quoted label, with
   `{{CLI}} decide --task {{TASK}} --worker <name> --key <topic> --choice <choice>`; add
   `--source <Japanese> --translation <English>` when every correction of that text must use
   that wording. Workers' briefs list them, and `next` prints those recorded since a worker's
   last bundle.
7. When a worker reports a defect outside its items in prose instead of an observation, record it with `{{CLI}} observe --task {{TASK}} --worker <name> --identity <line> --category <category> --note <reason>`; QA returns to deep review for it by itself.
8. When `status` reports `complete`, apply with the project helper's `qa --apply --wait 60`
   from your handoff. It applies every finding, and each question's proposal the user chose, as
   one reviewed text batch and saves a checkpoint commit. Open playtest or context questions
   wait for the user, who answers them in DazedTL's Text QA task; apply follows once every one
   has an answer, so tell the user once and keep waiting. `qa --undo <finding>` puts back one
   applied correction, and `qa --apply-again <finding>` applies an undone one again. Report a
   failed safeguard instead of working around it.
9. `not_translated` in `status` and `findings.json` counts Japanese that was never translated:
   no reviewer read it and QA did not correct it. When you report QA, name it as not reviewed,
   with what `findings.json` says about whether players can reach each file or plugin; never
   present it as checked.

## Worker

You are one reviewer, named in your prompt: give that name as `--worker` in every command, and never another.
Run each command below with `{{CLI}}` before it and `--task {{TASK}}`, as Commands lists them.

This brief holds the game's notes, translation quirks and the decisions every reviewer follows, and each bundle ends with the glossary entries its text uses, so read no other copy of the task's context and none of the game's files; `context --at` shows more of a scene when a line depends on text outside your bundle.

1. Claim a bundle with `next --worker <name>`, which prints all of it, followed by any decision recorded since your last bundle.
   Read all of it; when your tool cuts a long output, read the rest where the tool saved it, or print the bundle again with `show --bundle <id>`.
   Copy item IDs exactly as the bundle prints them.
2. Review it under its role's brief below: `screen-` bundles, checks ending in `-c1` included, as the screen reviewer, with their lint families as the group reviewer; `deep-` bundles as the deep reviewer; `sweep-` bundles as the group reviewer; and `editorial-` bundles as the editorial reviewer.
3. Write the result to `{{RECEIPTS}}` as `<bundle id>.json`, the only place you write results, and submit it with `accept --worker <name> --result <file> --next`, which accepts it and prints your next bundle.
   When accept refuses it, fix what it names and submit again; release a bundle you cannot finish with `release --bundle <id>`.
4. Review each bundle `accept` prints the same way.
   Submit your sixth without `--next` and stop, or stop when no bundle is left for you, and never while you hold one: the coordinator starts your next run, and a fresh run keeps your reviews sharp and their cost low.

End with one line: how many bundles you accepted, then the last line `accept` or `next` printed or an error you could not resolve.
Your results already hold your findings, so do not repeat them.

## Screen reviewer

Inspect every target in your bundle and report only exceptions; one accepted result covers the clean targets.
Another reviewer screens a sample of every reviewer's bundles again, and DazedTL compares the two; a reviewer whose checks found more problems it missed than it reported has every bundle screened again.
Review a check bundle like any other, without reading the result it repeats.

- A `scene` item is one complete command-list scene in order, each line numbered by its event
  command. Lines with an `id` are your targets; lines marked `[ctx]` were targeted in another
  scene, so report a problem this scene exposes on one as an observation naming the scene's
  command list and that number, such as `Map004.json#/events/9/pages/5/list/217`. Read every
  line so speaker continuity, callbacks, pronouns and comic timing stay visible. A `cluster`
  item is isolated non-dialogue text.
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
- A line's `glossary` names the glossary terms its source holds and its English lacks. Report it
  when the line names that character, place or thing another way; an ordinary word written like
  a term, or a name said as "you", is clean.
- A `motif-family` item gathers every translation of one recurring joke or wordplay rule from
  the translation quirks. Review it once: name one recognizable English joke mechanism and check
  that every nonliteral variant still reads as its callback before calling it `preserved`;
  otherwise name the affected variants in `suspect_ids`. Sharing a name is not a callback.
- An exception's verdict is `suspect` or `needs-context`, with categories and a short concrete
  note.

## Deep reviewer

Each item states the `deep_reasons` that escalated it. Return exactly one review per item. A
deep bundle prints each scene once after its items, numbering each line by its event command
and marking the lines each item's screen evidence names, and lists at most twelve of an item's
occurrences. Deep bundles open while
screening continues; an item whose screen evidence grew after its deep review comes back with
that `prior_review`, and your review replaces it.

- `checks` are deterministic findings that escalated the item, each with its evidence:
  `name-collision` (another entry of the same database shows the same English name) and
  `battler-name` (the way RPG Maker adds the battler's name leaves this battle message without
  a subject, or runs the name into it). Correct it, or review it `clean` with `evidence` that
  says why it stands. An MZ message whose
  check offers the `battler-name` source fix gets the `%1` its source forgot where the name
  belongs ("%1 was freed from the Illusion."); no other correction adds a code, and an MV
  message keeps a leading space. A `show-text-header` check means the Show Text header of the line's box
  likely shows the wrong speaker: settle it from the scene with a `source_fix`, or a `clean`
  review that says why the header is right.
- An `interface-fit` check means the game drew this text with too little room on a screen
  DazedTL captured while running a copy of the game: squeezed narrower than it needs, or cut off
  at its window's edge. Open every capture the check names and look at the text there. When it is
  cut off or hard to read, give a shorter `correction` with the same meaning, category `ui`; when
  it reads in full, review it `clean` and say what the capture shows. Text the capture shows cut
  off outside your items gets an observation.
- `screen_evidence` keeps the screening reviewer's reason and `scenes` every scene used to
  reach it; an `observation` is the reason a reviewer gave for a line outside its own items,
  and the `observation` deep reason marks an item it escalated. A `clean` review of such an
  item rebuts that reason concretely in its `evidence`; do not clear it because the problem is
  absent from the small `nearby_commands` window. Use
  `{{CLI}} context --task {{TASK}} --worker <name> --at <identity>` for more surrounding text.
- `motifs` names the family-level wordplay reviews; reconcile scene and family evidence.
  `motif-scene-contradiction` means a scene reviewer disputed a variant of a family called
  preserved, so every variant was reopened. Set `motif_ids` only when your correction or
  question concerns that joke mechanism.
- `actionable` is for a concrete, source-supported defect with a correction: severity
  `critical`, `high` or `medium`, and one category from {{CATEGORIES}}. A correction must pass
  apply's regression: DazedTL refuses one that adds a flag, changes a number, breaks a line
  structure or needs more rows than its `box` shows. An English ordinal ("First Stratum") may
  stand for a source number.
- A target's `box` is the text box it shows in, from the game's Line widths: `width`
  characters per line, `rows` it shows, and `wraps` when DazedTL rewraps a correction that has a
  line wider than the box, as the line width check does. Where it does not rewrap, keep each line
  within `width`. A longer wording that needs more rows than the box and the current text is
  refused, so shorten it instead.
- Actionable `fluency`, `voice` and `wordplay` reviews carry `editorial_basis`: the concrete
  reader-facing defect, the source, scene or guidance that makes it defective, and
  `not_preference: true`.
- Set `family_key` when lines share one underlying problem, such as `term:黄泉の巌`. When the
  problem recurs word for word, add a `sweep` rule that reproduces your correction exactly;
  DazedTL then finds every other line it changes for group review.
- `apply_identities` may limit a context-specific correction to some of the item's identities.
- A defect of a whole scene, such as narration that changes tense partway through, can need
  several of its lines changed together, since changing one line only moves the problem.
  Then give `scene_correction` instead of `correction`: one of the item's scenes, and each line to
  change by the command number the scene prints for it, with its exact current text and its
  correction.
  Include the item's own line there; the lines apply and undo as one correction, and each must
  pass the regression checks above.
  DazedTL refuses a line in a scene or item a reviewer declined, and applies each line's accepted
  lint fixes on top.
  Review another item whose line it changes as usual; when the scene correction already fixes
  it, call it clean and say so in `evidence`.
- `uncertain-playtest` is for runtime or context uncertainty no evidence settles; say what must
  be checked in `evidence`, and give a `correction` when you have a proposal the user may choose
  instead of the current text. These become the questions the user answers in DazedTL.
- A slip in the Japanese source itself gets a `source_fix`: a Show Text header showing the wrong
  speaker's face or name, a database text stating a number its own entry contradicts, or an MZ
  battle message missing the `%1` that shows its battler's name.
- A deep item's `lint` names mechanical fixes already accepted for the line; DazedTL applies
  them to your correction too, so write it for meaning and voice.

## Group reviewer

A `lint-family` item lists one mechanical family's exact fixes, and a `sweep-family` item lists every other line an accepted correction's sweep rule changes, beside that correction.
Check them as a group and reject only the proposals that would harm their line, such as a sentence start, a system label or a style this game deliberately keeps, with a note.
A `lint:glossary-term` proposal writes the glossary's English over another rendering of a term, and its `WHY` names the term.
The glossary is authoritative, so accept it where the line names the glossary's character, place or thing; reject it where the Japanese there is an ordinary word, or the proposal replaced other words or reads wrong, and add an observation when the line still names the term another way.
Every proposal you neither reject nor decline becomes a finding.

## Editorial reviewer

This is the last pass before corrections are applied. For each finding compare the source,
current text, correction, evidence and nearby game text, and confirm publication-ready meaning,
natural English, speaker voice, terminology and honorific policy, runtime controls, line breaks
and fit; each target's `box` gives the width and rows it shows in. A correction of text the
game drew with too little room comes with its screens captured again with the correction in
place: open them, and `revise` one the game still squeezes or cuts off. `accept` a correction that fixes a concrete defect, `revise` it with a smaller or more
natural `replacement` for the same defect, and `withdraw` it when the current and proposed
wordings are equally valid. For `fluency`, `voice` and `wordplay`, confirm the `editorial_basis`
independently. An item's `conflicts` name corrections that contradict each other, the
translation quirks, a recorded decision or a structured label: revise until they agree, or
accept with a note when the contexts need the difference. A Show Text header fix is accepted or
withdrawn, never revised.

A scene correction changes several lines of one scene together, and its item prints the whole
scene with each changed line's fix.
Judge the lines together and accept or withdraw them as one correction, or `revise` with
`replacements` for the lines that need it, each by its command number and exact current text; a
line's current text as its replacement leaves that line as it is.

## Commands

Prefix every command with `{{CLI}}`:

- `status --task {{TASK}}`, `brief --task {{TASK}} --role <screen|deep|group|editorial|worker>`
- `next --task {{TASK}} --worker <name> [--helper <name>] [--bundle <id>] [--skip-declined]` claims a bundle and prints it compactly; `show --task {{TASK}} --bundle <id>` prints it again
- `accept --task {{TASK}} --worker <name> --result <result.json> [--next]`, `release --task {{TASK}} --bundle <id>`
- `decline --task {{TASK}} --worker <name> [--helper <name>] --bundle <id> --item <id> --reason "<one line>"`, repeating `--item` and `--reason` together, for items of a bundle no other worker holds
- `advance --task {{TASK}}` and `finalize --task {{TASK}}`, each with `--skip-declined` when no worker on another helper will take a declined bundle
- `context --task {{TASK}} --worker <name> --at <identity or command list>` for read-only
  surrounding text; scenes a reviewer declined are left out unless your assigned bundle prints
  them
- `decide --task {{TASK}} ...` and `decisions --task {{TASK}}`
- `observe --task {{TASK}} --worker <name> --identity <line> --category <category> --note <reason>`,
  with `--category` repeated for more, to observe a line outside every result
- `rebuild-deep --task <earlier task>` when DazedTL reports that its QA rules changed after an earlier task's screen was complete: it reuses that screen's validated results and checks in a new task, where any check the current rules add waits for a reviewer

## Result formats

Every result names its `bundle_id` and the `bundle_sha256` that `next` returned.
A declined item is `{"id": "<item id>", "reason": "<one line, no game text>"}` in a screen, group or editorial result's `declined` list, and a deep review with `"disposition": "declined"` and a `reason`.
The `id` may name one lint proposal, sweep candidate or motif variant instead; review the rest of its family, leaving the declined one out of `rejected` and `suspect_ids`.
Declining every one declines the family, which then gets no review.

Every result may carry `observations`, each
`{"identity": "<line>", "categories": ["speaker"], "note": "<one-line concrete reason>"}`. The
line is an inventory identity, with or without its `@` checksum, or the event command or
database field that holds it: a command list from `context` with the command number, such as
`Map007.json#/events/14/pages/2/list/217`, or a field such as `States.json#/42/message1`. An
observation cannot name a line the result judges itself, such as a screen target, a deep item's
listed occurrences, a sweep candidate or a finding's targets.

Screen:

```json
{"schema":"{{SCREEN_SCHEMA}}","bundle_id":"screen-0001","bundle_sha256":"...","reviewed_all":true,"exceptions":[{"id":"scene-target-...","verdict":"suspect","categories":["meaning"],"note":"short concrete reason"}],"motif_reviews":[{"id":"motif-...","disposition":"preserved","note":"The joke mechanism and why every variant keeps it.","suspect_ids":[]}],"lint_reviews":[{"id":"lint-family-...","rejected":[],"note":""}],"declined":[],"observations":[]}
```

Deep:

```json
{"schema":"{{DEEP_SCHEMA}}","bundle_id":"deep-0001","bundle_sha256":"...","reviews":[{"id":"...","disposition":"actionable","severity":"medium","category":"voice","family_key":"term:...","motif_ids":[],"evidence":"concrete reason","correction":"Corrected text.","apply_identities":[],"editorial_basis":{"defect":"...","source_support":"...","not_preference":true},"sweep":{"find":"exact current text","replace":"exact corrected text","source_has":"optional Japanese"}}],"observations":[]}
```

A clean review keeps `severity` null, `category` and `family_key` empty and `correction` null.
A scene correction keeps `correction` null and `apply_identities` empty, and names lines of one of
the item's scenes by the command numbers the bundle prints:
`"scene_correction":{"scene":"S1","lines":[{"command":197,"current":"exact current text","correction":"Corrected text."},{"command":210,"current":"exact current text","correction":"Corrected text."}]}`.
Source fixes are `"source_fix":{"kind":"show-text","face_name":"<a face the game shows>","face_index":0,"name":"<nameplate, empty for narration>"}`
with category `speaker`, `correction` null and exactly one `apply_identities` entry, or
`"source_fix":{"kind":"database-numbers"}` on a correction that changes a number only to one of
its locator's `database_values`, or `"source_fix":{"kind":"battler-name"}` on a correction that
adds only the `%1` an MZ battle message's source lacks.

Group (lint items go in the screen result's `lint_reviews`):

```json
{"schema":"{{SWEEP_SCHEMA}}","bundle_id":"sweep-0001","bundle_sha256":"...","reviews":[{"id":"sweep-family-...","rejected":[],"note":""}],"declined":[],"observations":[]}
```

Editorial:

```json
{"schema":"{{EDITORIAL_SCHEMA}}","bundle_id":"editorial-0001","bundle_sha256":"...","reviews":[{"id":"QA-0001","verdict":"accept","note":""},{"id":"QA-0002","verdict":"revise","replacement":"Publication-ready wording.","note":"why"},{"id":"QA-0003","verdict":"withdraw","note":"why"},{"id":"QA-0004","verdict":"revise","replacements":[{"command":215,"current":"exact current text","replacement":"Publication-ready wording."}],"note":"why"}],"declined":[],"observations":[]}
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
