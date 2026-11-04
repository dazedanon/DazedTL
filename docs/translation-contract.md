# Translation adapter contract

The interface between DazedTL and the assistant that runs an Assistant-led translation, for that assistant and for authors of engine adapters.
Len's skill and its engine references own translation methodology, the generated starting prompt gives the assistant its steps, and `scripts/project.py --help`, with each command's `--help`, documents every command.
No API credentials belong in adapter files or prompts.

## Project helper

The assistant runs the generated command prefix with `scripts/project.py`, which talks only to the running app's authenticated loopback endpoint, never through a proxy or redirects.
Keep DazedTL open; after it reopens, the same command reads the new connection and resumes saved state.

- Start with `state`: it reports the portable options, Git state, whether the original game files are recorded, saved progress, drafts, frozen runs and any run that needs recovery.
- Record the engine with `identify` and a project-relative investigation report.
- Commands that start work return a saved job ID, and `run --wait MINUTES` waits in one command until its state changes.
- A lost reply may follow a completed action: read the saved state, runs and the task's active request before retrying a change or a paid submission.
- The helper can't approve spending, publish plugin files or start what only the user starts, such as Start over, going back or undoing.

The helper also drives the tasks the app hands out:

| Command | What it does |
| --- | --- |
| `plugins` | Reads the active Plugin files request; `--continue-request ID` checks the saved report and returns the next request, until every plugin file is done and every label Text QA found too long is shortened or kept. `--capture` plays the game with the working copies and shows how each label draws. |
| `images` | Runs Assistant-led's Images steps, `--scan`, `--investigate`, `--translate` and `--apply`, and `--status` names the next. Images decoded from the game's archives go in a game folder named with `--scan --root`. |
| `qa` | Text QA for RPG Maker MV/MZ and VX Ace: `--prepare` prepares or resumes the task, whose README the assistant follows, and `--apply` applies the finished findings as a checkpoint, with `--wait` for the user's answers; `--undo` and `--apply-again` take back or reapply one correction. On other engines, `qa --check` runs the text-only checks. |
| `playtest` | The release playtest for MV/MZ: `--run` plays the game in a hidden window, `--stops FILE` adds places to visit, and `--fix` writes the fixes plugin only once a play with it breaks nothing new. |

### Sandboxed connections

A network sandbox can block loopback even while DazedTL is running.
The starting prompt includes the permission and recovery steps, and the helper repeats them on a connection failure.
Use the assistant's normal permission flow for the helper, and check access with the read-only `state` command before diagnosing an app outage.

## Game setup

- DazedTL keeps the original game's files in the game's own Git repository under the private ref `refs/dazedtl/originals`, which no branch push sends ([original_files](../backend/dazedtl/compatibility/original_files.py)).
  It records a game in the background when it opens it, and the assistant runs `record_original`, which waits for that record, before changing game files with its own tools.
- RPG Maker preparation uses the shared helper; VX Ace and other formats need their engine's extraction or conversion first.
- Git setup needs a source version and a reviewed runtime manifest.
- The untranslated flag attests that the source was inspected; it isn't permission to label English as an original.

## Source units

Len's extractor saves everything in scope as source units, and organize groups them into requests, so the assistant never reads or rewrites the game's text to group it.
A unit is one message as the player reads it, with lines the engine stores separately, such as RPG Maker's consecutive 401 commands, joined by newlines.
`units-format` prints an example, and [organize.py](../backend/dazedtl/translation/organize.py) holds the validator and the grouping.
The file is an object with `version` 1 and `units`, a list in play order:

| Field | Contract |
| --- | --- |
| id | Required. Unique single-line text of at most 240 characters that the engine's injector maps back to its location. |
| scene | Required. The engine's scene, such as an event page, common event, scenario label or table. A scene's units stay together. |
| source | Required. The Japanese message exactly as the injector will replace it. |
| group | The file or area a scene belongs to; defaults to the scene. Small scenes of one group share a request. |
| kind | dialogue, narration, ui, or unknown (the default) when the extractor cannot tell. |
| speaker | A name the extractor's rules found, or null (the default). UI has no speaker. |
| field | A section.key template from data/translation_contexts.json that applies to the whole scene, such as database.item. |
| tokens, max_lines, max_characters | Protected literal strings present in the source, and layout bounds. |

- Speakers come only from the engine's own evidence, such as nameplates and face or speaker codes: never inherit the previous speaker or infer identity or gender from speech style, and leave unknown speakers unknown.
- Keep nameplate text separate from speaker labels, and don't deduplicate lines by their Japanese text.
- Move game text only with scripts, never by pasting or retyping it.

`organize --input <units file>` packs whole scenes of one group and field into requests, compiles and prices them, and replies with counts only; add `--complete` once the units cover the [census](#census-and-scope).

- A request holds at most the model's entries per request and 8,000 source characters in the API modes, or 250 lines and 12,000 characters in Assistant only.
  In the API modes a scene of more than 10 lines gets its own request, and a larger one splits into parts that carry its earlier lines as context.
- A unit without source letters, such as 「……」 or ！？, joins no request: DazedTL writes it in its English form (`unsent_line` in [results](../backend/dazedtl/translation/results.py)).
- organize refuses units that split most multi-line RPG Maker messages into a unit per line, since each unit repeats the shared guidance.

## Census and scope

Scope is mechanical: DazedTL counts the original game's Japanese text itself, from the recorded prepared game, and the assistant never decides what is in scope.
`census` saves that count, and [census.py](../backend/dazedtl/translation/census.py) holds its readers, rules and coverage.

- It reads RPG Maker data and the plugins a game loads, JavaScript, KAG/Tyrano and Ren'Py scripts, decompiled YU-RIS scripts, HTML, text and YAML, and opens RGSS, asar, unencrypted xp3 and Wolf archives.
  For containers it can't open, such as Unity, Unreal or encrypted archives, `census --decoded` reads a folder Len's decoder wrote.
- Coverage counts Japanese runs by occurrence: each must be in a unit, be a term of the game's glossary, or be set aside by a rule.
- Built-in rules set aside text players never see, such as comments, labels, asset names and readmes; comment lines a game's plugins show players, such as MPP_ChoiceEX's choice help, are player text ([rpgmaker_markers](../backend/dazedtl/engine/util/rpgmaker_markers.py)).
- The assistant can add rules in `.dazedtl/len-method/work/scope-rules.json`: version 1, with rules of `kind`, `field` and `reason` (asset_name, identifier, comment, script_code, not_displayed or other_language), each optionally limited to a `file` pattern or exact `values`.
  Rules never set aside dialogue, choices, names or other text players read in formats DazedTL reads itself.
- `census-uncovered.json` lists each uncovered location, and apart from those, each line of Japanese punctuation without letters that no unit holds.
- `organize --complete` is refused without a current census, while archives still need a decoded dump, or while anything is uncovered, and packaging needs `organize --complete` against the latest census.
  A game update or a new census version makes the census stale until it runs again.
- Content is never a reason to leave text out: the assistant [declines](#declined-requests) a request it won't translate, which keeps its lines in scope.

## Source plan

Organize writes and compiles the plan.
A plan written by hand compiles the same way with `compile --input`, `plan-format` prints a minimal one, and [requests.py](../backend/dazedtl/translation/requests.py) holds the validator; compile refuses a plan organize wrote, since only organize knows the lines it kept from earlier requests.

| Field | Contract |
| --- | --- |
| version | 2 for new source plans. Existing saved runs with unversioned inputs remain readable and can resume when their frozen requests are unchanged. |
| complete | True only when the selected scope's entire planned corpus has been independently audited. API quoting requires this. |
| inputs | Unique project-relative source and guidance files. Use immutable source exports, not a store whose translation columns will change. |
| batches | Ordered coherent batches, each with a stable unique id and an ID-to-Japanese sources object. |

- Every batch needs `kinds` and `speakers` with exactly the IDs of its `sources`, by the rules for [source units](#source-units); narration may name a known narrator without becoming dialogue, and unknown speakers never raise review flags.
- A batch may add `source_context`, `scene_context`, an `instruction_key` from the field templates, and `constraints` by source ID: `tokens`, `max_lines` and `max_characters`; pixel fitting stays with the engine's renderer.
- Optional `qa_notes` map source IDs to short notes, 1 to 2,000 characters, about a concrete ambiguity that could change meaning, gender, perspective or a plot fact; every mode gets them as uncertain context, and they appear beside the saved translations.
  An unknown speaker alone is no reason for a note.
- Keep occurrence identity and scene order; an exchange that spans requests carries the surrounding source of its scene.
- The compiled run holds the full instructions, glossary and speaker guidance, field instructions and source context, and for API requests the exact provider payload and settings; source is never silently truncated.
- Tracked sources bind to their original-branch blobs and other inputs to their bytes, so a changed source version, guidance, context or scope needs a new plan before new paid work; saved plans, results and approvals are never rewritten.

## Results and corrections

- `request --run ID --index N`, or `--request-sha256`, shows a request, its fingerprint and any accepted result.
- An agent's receipt holds `request_sha256` and `translations`, an object with exactly the requested IDs and string values; save it in the game workspace and pass its path to `accept`.
- accept rejects missing, duplicate, unexpected or empty lines, a line that fails Guided's content check ([validate_translation_content](../backend/dazedtl/engine/util/translation.py)), and one that changes its source's control codes or the scopes they open and close (`validate_unmasked_control_codes` in [runtime_text](../backend/dazedtl/engine/util/runtime_text.py)); only a ruby may be translated or left out.
  Where a request shows a name code as the actor's name, writing the name is accepted.
- An API run keeps a rejected line in its source text and accepts the rest of its request ([results](../backend/dazedtl/translation/results.py) `kept`); a request with no passing line fails, and nothing is sent again by itself.
- A correction supplies `replaces_sha256` equal to the current `result_sha256`: the previous result is archived, and review, injection and QA of the changed lines become pending.
  A line organize kept from an earlier request is corrected through the run that kept it (`reused_request` in [service](../backend/dazedtl/translation/service.py)).
- An ordinary retry can't overwrite an accepted translation; record a source-checked `review` only after doing it, and never regenerate hashes to make stale work count as current.
- Accepted records live under `.dazedtl/len-method/work/accepted`, with their correction history; one checked under older refusal rules is read again under the current ones.
- `results --run ID` writes the run's translations by line ID to `.dazedtl/len-method/work/results/ID.json`, with the cleanup and automatic lint fixes Guided gives every line, while the accepted record keeps each translation as accepted.
- For MV/MZ, `write_rpgmaker` writes that export into the game with Guided's punctuation and spacing (`written_message` in [rpgmaker_blocks](../backend/dazedtl/engine/util/rpgmaker_blocks.py)), and refuses once the extracted lines it was organized from change.
- The app's progress export is a derived view, never a replacement for an engine's extraction or injection data.

## Declined requests

In Assistant only, `decline --run ID --batch ID --reason TEXT` sets aside a request the assistant won't translate, so it carries on with the rest; the reason is one line of at most 300 characters, without game text.
Decline rather than soften, shorten or leave out lines; accept refuses a refusal note in place of a line.
Progress then offers the user an API estimate or a prompt for another assistant to translate only those requests, and either way the translations land in the same accepted store.

## API execution and recovery

- Only the user approves spending, with the button on Progress: `start` resumes only a run approved there, and each compile or organize replaces the estimate waiting.
- Switching models within the connection, or between Batch and Live, reprices a waiting quote whose requests stay the same; any other settings change outdates it.
- A quote is an estimate, not a guaranteed bill: it counts input as Guided's estimate does and output as a multiple of the source ([`OUTPUT_ALLOWANCE`](../backend/dazedtl/engine/util/translation.py)).
- New runs retry a confirmed refusal once with clarifying context, billed in the selected mode, and a second refusal stays unresolved.
  A note in place of a line, or the model talking about its task, is a refusal, never game text ([refusals](../backend/dazedtl/translation/refusals.py)).
- Live and Batch use the same compiled content.
  Pausing stops locally and never cancels a remote job; `stop --cancel-provider` cancels a Batch where the run's `can_cancel_provider` allows it, which OpenRouter's never does.
- Results missing from a finished OpenRouter Batch wait for Retry collection and are never sent again automatically, and results DazedTL downloaded stay after OpenRouter deletes its copy.
- An uncertain request is never sent again automatically: attach its Batch job with `attach-batch`, or for a Live call check the provider first, then `resolve-uncertain --retry-reviewed` allows a new quote for the remaining work.

## Translation files

A translation file carries a project's lines out of DazedTL and back in every method: the Project page's Export and Import, and a Manual project's input.
[translation_file](../backend/dazedtl/translation/translation_file.py) holds the reader, the writer and the import rule, and [exchange](../backend/dazedtl/translation/exchange.py) each method's lines.

- JSON: `format` `"dazedtl-translation"`, `version` 1, `languages` with `source` and `target`, `lines`, and optionally `glossary` entries of `section`, `source`, `translation` and `note`; `game` and `exported` only describe it.
- A line has the fields of a [source unit](#source-units) and `translation`, text or null.
  Manual checks each line as organize checks a unit; an import needs only `id` and `source`.
- CSV: a UTF-8 header row naming `id`, `scene`, `group`, `kind`, `speaker`, `source`, `translation`, `field`, `max_lines` or `max_characters`, at least `id` and `source`; an empty cell is null, and tokens and the glossary need JSON.
- A plain units file reads as a translation file without translations.
- Manual's **Save example…** writes `example`, organize's example units as a translation file.

IDs are the units' own in Assistant-led and Manual.
Guided names a line `<file>#<JSON pointer>` into the original game file: a value's own, and for a message, scrolling text or comment its first command's, with `/parameters/4` after it for a name box and `~<n>` for a later part, so translated and untranslated copies of one game version share IDs ([guided_lines](../backend/dazedtl/translation/guided_lines.py)).

An import writes a line only where the project's source at its ID is the file's exactly and its translation passes the checks `accept` applies; a file naming another language pair is refused, and the import must read the bytes its preview read.

- Assistant-led and Manual save each import as a receipt and request of its own (`save_import` in [unit_results](../backend/dazedtl/translation/unit_results.py)), read as a run's.
- Guided writes them into its working copies as it writes a reply's lines (`game_line`), with their sources in `_original`, and Apply fits them; choice help and note labels aren't imported yet.
- A spreadsheet error value, such as `#NAME?`, is skipped.
- It ends API runs that would send its lines again, refused while a provider may still answer one (`retire` in [jobs](../backend/dazedtl/translation/jobs.py)).
- The glossary gains, through the game-write gateway, terms no row covers.

A Manual project's loaded file becomes its units ([manual](../backend/dazedtl/translation/manual.py)), and its estimate organizes the lines without a translation in Batch or Live.
Its runs freeze `method: manual`: the user's tools decide the scope and write the text, so they need no census, Git baseline or progress report.

## Delivery and future versions

- Report progress in the maintained format after the first state read, after saved milestones and before waits or a handoff; reports are refused only while an operation changes the game.
  Counts describe saved units, while extraction coverage, review, images, injection, QA and packaging are separate evidence, so report declined lines, set-aside counts and unresolved extraction explicitly.
- Save the measured Line widths with `line_widths`, then stage MV/MZ JSON and run `write_rpgmaker`, which keeps `_original` and fits the text; saving widths again refits what it wrote.
- When the official source changes, `rebase_rpgmaker` needs the expected original commit and source bytes identical to it; native formats use their own source and injection sidecars.

Every change DazedTL makes to the game, through these operations or the app, is a [checkpoint](architecture.md#checkpoints).

- The app also checkpoints the assistant's own work at each progress report and when a translation run ends, named for the phase the last report named, and `write_rpgmaker` and `rebase_rpgmaker` wait for that checkpoint.
- Undoing a phase's checkpoint, or going back past it, reopens that phase and every later one, and a game update reopens extraction and the phases after it ([progress_report](../backend/dazedtl/translation/progress_report.py)).
- Changes made outside DazedTL get a checkpoint of their own before the next change DazedTL makes.
- Don't create full workspace copies or checkpoint ZIPs.
  DazedTL takes no new backups: `backups` lists older ones, and `restore_backup` restores one into a new folder outside the game without overwriting anything; the [user guide](user-guide.md#backups-from-before-checkpoints) covers recovery without the app.

Packaging:

- `package` needs current reported QA, saves outstanding changes and builds a local patch from the files the translation branch tracks; it creates no remote and never pushes or uploads.
- Checkpoints, packages and QA records carry DazedTL's own files the game holds, such as GameUpdate's files, the update check, Forge and the playtest's fixes plugin, so manifests need not list them; `gameupdate/patch-config.txt` ships only in a release of the verified public version (`public_version` in [release](../backend/dazedtl/translation/release.py)).
- A package refuses a `plugins.js` that loads a plugin neither the patch nor the original game holds, and a `js/main.js` that doesn't match the fixes plugin, since players' game would stop at start.
- TL Inspector stays on the translator's computer: no patch carries it, and `plugins.js` never lists it.

For an official update, `stage_update` records the new release in the game's Git as a separate working copy, as a patch when it holds fewer than half the game's files unless `patch` says otherwise.
Prepare it there, then run `version_preview` and `version_apply` with the saved preview ID; `version_continue` and `version_abort` use Git's recovery state.
After the update, `version_handoff` returns the post-update task: the starting prompt's steps from census on, in the project's mode and language pair.
Reuse unchanged translations with their source and context evidence, never by array position alone.
