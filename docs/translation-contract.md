# Translation adapter contract

This is the interface for engine adapters and the assistant receiving the starting prompt.
Len's maintained skill and its engine references remain the source of translation methodology.
The app supplies the invocation, project ID and workspace path; no API credentials belong in adapter files or prompts.

## Project helper

Keep the app open and use the generated command prefix with scripts/project.py.
Its --help and operation --help describe available commands and operation arguments.
The helper talks only to the profile's authenticated loopback endpoint and does not use a proxy or follow redirects.
After reopening the app, the same invocation reads the new connection descriptor and resumes saved state.

The single plugin task uses `plugins` to read its active request and `plugins --continue-request ID` after saving each request-bound report.
Continuation validates findings, prepares scoped working copies and returns the next request, for whatever is left, to the same agent session until every plugin file is done and every plugin label Text QA found too long for the screen is shortened or kept.
While a request asks to shorten labels, `plugins --capture --wait MINUTES` plays the game with its working copies served in place of the game's files and returns, for each label, the text its screen draws now, whether it fits and the capture.
Saved progress appears through the app observer.
The helper cannot publish plugin files; final runtime Apply stays in the app.
Read the active request before resuming after a lost reply.

An Assistant-led project that includes image text runs the Images steps with `images --scan`, `--investigate`, `--translate` and `--apply`; `images --status` names the next one.
On a game whose images sit in archives, the assistant decodes them with Len's tools into a folder in the game and names it with `images --scan --root <folder>`, as `census --decoded` names decoded text; the steps then read and write that folder, and the assistant packs it into the archive again.
Investigate and Translate save the same request-bound tasks Guided's Images task hands out, as files to follow, and the next step reads their saved reports.
The assistant also does the user's part: its recommendations stay the list, and Apply publishes the translated, reviewed images, whose checkpoint takes the files it changed into the patch.
The app turns the Image Manager's list into the image records that progress reports and packaging count.
An image in the list counts until it is applied, one its translation skipped drops out, and the records complete once every image has a finding.
Images is its own progress phase; a report that leaves it out gets it from these records, complete once they are and active once they list an image.
Guided projects keep these steps in their Images task.

Text QA for RPG Maker MV/MZ and VX Ace runs with `qa`: `qa --prepare` prepares or resumes the task, whose README the assistant follows to review, and `qa --apply` applies the finished findings through the app as a checkpoint of their own; `qa --status` names the next step.
For an Assistant-led project, `qa --status` also lists under `labels` the text QA's captures show squeezed or cut off that QA holds no line of, such as a plugin's menu command, with each screen and capture.
The assistant shortens those in the plugin files before `qa --apply` and runs `qa --prepare` again, which keeps the review and captures the screens again; a label that still shows squeezed is listed again.
Apply waits while a playtest or context question is open: the user answers it in DazedTL's Text QA task, and `qa --apply --wait MINUTES` applies once every answer is in.
`qa --undo QA-0001` puts back one applied correction and `qa --apply-again QA-0001` applies an undone one again, each with its own checkpoint; `qa --choose QUESTION keep` or `use` records an answer the user gave the assistant.
`qa --checkpoint` is kept for assistants started before then and changes nothing.

The release playtest for RPG Maker MV/MZ runs with `playtest --run --wait MINUTES`, which checks the game's files, plays it in a hidden window and returns where it stands; `--report` names the report file, and `playtest` alone the next step, the fixes file and the saved stops.
`--stops FILE` adds places after the standard tour, a JSON list of `{"title", "do"}` objects: `map` with `map`, `x` and `y`, `event` with `event` (and `map`), `common-event` with `id`, `battle` with `troop`, `scene` with `scene`, or `script` with `script`, each optionally with `switches`, `variables` and the `seconds` to play after it.
The stops given replace the saved ones, which every later run visits, and `[]` clears them.
`playtest --fix --wait MINUTES` plays the game with the fixes file, a working copy of the game's `js/plugins/DazedTL_Fixes.js`, in its place and with `js/main.js` loading it after the game's plugins.
Only when that play still plays, stops nowhere new, reaches as many places and no longer shows something the last playtest found does it write both, as one batch and one checkpoint, which Guided's History undoes; the play then becomes the latest report, and otherwise its reason is the step's failure.
`playtest --checkpoint` is kept for assistants started before then and changes nothing.
Its findings in translated text reach text QA by themselves; plugin text the playtest saw drawn goes back to Plugin files, whose remaining work `plugins --task` hands out, never a recheck of every decision as the app's Copy gives once nothing is left, and `plugins --apply` applies as Apply to game does; the rest name the step that fixes them.

### Sandboxed connections

A network sandbox can block loopback even when DazedTL is running.
The generated starting prompt includes the permission and recovery procedure; the helper repeats it on connection failures.
Use the assistant's normal permission flow for the helper and verify access with the read-only `state` command before diagnosing an app outage.
A lost response may follow a completed action, so inspect saved state and runs before retrying a mutation or paid submission.

### Saved state and setup

Use state before starting.
Every Assistant-led helper call also records when the assistant last reached the project, which Progress shows before its first report.
Starting a project over is the user's choice in the app; the helper cannot.
It reports the portable options, current Git state, whether the original game files are recorded, saved progress, pending drafts, frozen runs, and any saved phased run requiring recovery.
Record the detected engine with identify and a project-relative investigation report.
Operation commands return saved job IDs; inspect them with run until they complete, fail, stop, or await approval or provider results.
`run --wait MINUTES` waits in one command and returns as soon as the run's state changes, so a long Batch costs the assistant one turn per wait instead of one per poll.

DazedTL keeps the original game's files in the game's own Git repository, under the private ref `refs/dazedtl/originals`, which no branch push sends ([original_files](../backend/dazedtl/compatibility/original_files.py)).
It records the game as it is in the background once it opens a game whose Git is not set up, and an assistant runs record_original, which waits for that record, before changing the game's files with its own tools.
Git setup records the prepared game too, and a game update the new release; projects set up before then keep reading their backups ([originals](../backend/dazedtl/translation/originals.py)).
RPG Maker preparation uses the existing shared helper; Ace and other formats require their engine's extraction/conversion route first.
Git setup requires a source version and a reviewed runtime manifest for a fresh baseline.
The untranslated flag is an attestation after source inspection, not permission to label English as an original.

## Source units

Len's extractor saves everything in scope as source units, and organize turns them into requests, so the assistant never reads or rewrites the game's text to group it.
A unit is one message as the player reads it, with the lines an engine stores separately, such as RPG Maker's consecutive 401 commands, joined by newlines.
Use units-format for an example.
The authoritative validator and grouping are in [organize.py](../backend/dazedtl/translation/organize.py).
The file is an object with version 1 and units, a list in play order; each unit has these fields:

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

Speakers come only from the engine's own evidence, such as nameplates and face or speaker codes.
Do not inherit the previous speaker or infer identity or gender from speech style; unknown speakers are valid.
Keep nameplate text separate from speaker labels, and do not deduplicate lines by their Japanese text.

Run organize --input with the units file, adding --complete once the units cover the [census](#census-and-scope).
It packs whole scenes of one group and field into requests: in the API modes of at most the model's entries per request and 8,000 source characters, and in Assistant only of up to 250 lines and 12,000 characters, Len's batch size, since the assistant reads each request's shared guidance again.
In the API modes only scenes of at most 10 lines share a request; a longer scene gets its own, so another scene's speakers and subjects can't bleed into it.
A request holding several scenes names which lines belong to each, so the model keeps their speakers and context apart.
A larger scene splits into even parts, each carrying the scene's earlier lines as source context.
A unit whose source holds no source letters, such as 「……」 or ！？, joins no request and is never priced: DazedTL writes it itself as Guided writes text it never sends, every mark in its English form ([results](../backend/dazedtl/translation/results.py) `unsent_line`), and marks its export row converted.
A unit stays in a request when that form would change one of its protected tokens.
Requests hold a number of units, each repeating the shared guidance, so organize refuses units that split most RPG Maker messages of three or more lines into a unit per line.
Each request takes its first unit's ID, and the plan is saved under .dazedtl/len-method/work/plans by its content.
DazedTL then compiles and prices the requests in an operation that Progress shows, and the helper waits for the run it saves.
The reply holds counts only; errors name unit IDs without repeating game text.
Move game text only with scripts, never by pasting or retyping it.

## Census and scope

Scope is mechanical: DazedTL counts the original game's Japanese text itself, and the assistant never decides what is in scope.
The census helper command runs an operation that reads the recorded prepared game, never the working copy, and saves its count in the profile.
The authoritative readers, rules and coverage are in [census.py](../backend/dazedtl/translation/census.py).
It reads RPG Maker MV/MZ JSON and plugins, JavaScript, KAG/Tyrano and Ren'Py scripts, decompiled YU-RIS scripts, HTML, text and YAML.
It opens RGSS archives and XP/VX/Ace data, Electron asar and unencrypted xp3 archives, and Wolf data through the bundled WolfDawn.
It reads YU-RIS archive indexes, so only archives holding scripts or text need a decoded dump.
For containers it can't open, such as Unity, Unreal or encrypted archives, census --decoded reads a game-relative folder that Len's decoder wrote, and Progress says the count came from it.

Each counted string has a kind and a field naming its structure, never a map, event or scene.
Coverage counts Japanese runs by occurrence: each must appear in a unit, which holds the game's text exactly, be a term of the game's own glossary, or be set aside by a rule.
Built-in rules set aside text players never see, such as comments, labels, asset names, switch names and the readmes beside a game; mod loaders and runtimes installed beside it, such as BepInEx, are not read.
RPG Maker MV/MZ comment lines that the game's plugins show players, such as MPP_ChoiceEX's choice help, are player text under their own field, `*[code=408:help]`, by the markers [rpgmaker_markers](../backend/dazedtl/engine/util/rpgmaker_markers.py) names; the marker comment and other comments stay set aside.
The plugin settings that list those markers are set aside too, since the plugin finds the comments by them.
Of MV/MZ plugins it counts only those the game loads, by the loader rule Plugin files follows ([rpgmaker_plugin_registry](../backend/dazedtl/engine/util/rpgmaker_plugin_registry.py) `loads`): a disabled entry, a plugin's later entry and the file of a plugin the list never loads are left out, and so are DazedTL's own Set up files.
Comma or tab separated text is read by column; a table translating its Japanese first column into another language names that column table:key, and a built-in rule sets aside a Chinese column, whose characters Japanese runs can't tell apart.
The assistant can add rules in .dazedtl/len-method/work/scope-rules.json, as version 1 with rules of kind, field and reason (asset_name, identifier, comment, script_code, not_displayed or other_language), each optionally limited by file, a path pattern, or values, exact runs such as a script format's Japanese command words.
Rules work on every kind, including decoded dumps, generic JSON and plain text, and never set aside dialogue, choices, names or other text the player reads in formats DazedTL reads itself.
Lines holding Japanese punctuation but no letters, such as 「……」 or ！？, are listed apart as unsent, outside coverage: census-uncovered.json lists those no unit holds, so the assistant extracts them and DazedTL writes them in their English form.
organize --complete is refused without a current census, while archives still need a decoded dump, or while anything is uncovered; .dazedtl/len-method/work/census-uncovered.json lists each uncovered location.
Rules apply before extraction, so an identifier a rule sets aside never uses up the unit for the same words where the player reads them.
Once a game update records a new prepared game, or DazedTL raises the census version because it counts other text, packaging is refused until census runs again, and Progress reads the coverage as stale until organize runs after that census ([run_compiler](../backend/dazedtl/translation/run_compiler.py)).
Packaging requires organize --complete against the latest census, and a progress text export counting at least the units it accepted.
Content is never a reason to leave text out; the assistant declines a request it won't translate, which keeps its lines in scope.

## Source plan

Organize writes this plan and compiles it; a plan written by hand compiles the same way, and plan-format shows a minimal one.
compile refuses a plan organize wrote, which leaves out the lines organize kept from earlier requests, so only organize compiles it ([organize](../backend/dazedtl/translation/organize.py) `owns`).
The authoritative validator is [requests.py](../backend/dazedtl/translation/requests.py).
The JSON object has these fields:

| Field | Contract |
| --- | --- |
| version | 2 for new source plans. Existing saved runs with unversioned inputs remain readable and can resume when their frozen requests are unchanged. |
| complete | True only when the selected scope's entire planned corpus has been independently audited. API quoting requires this. |
| inputs | Unique project-relative source and guidance files. Use immutable source exports, not a store whose translation columns will change. |
| batches | Ordered coherent batches, each with a stable unique id and an ID-to-Japanese sources object. |

Every batch requires kinds and speakers, both with exactly the same IDs as sources, following the rules for [source units](#source-units).
Narration may carry a known narrator's identity without turning it into spoken dialogue.
Unknown speakers never generate review flags automatically.

A batch can also have source_context for preceding Japanese; scene_context for evidence-based scene and runtime-substitution notes; an instruction_key from the existing field templates; and constraints keyed by source ID.
Supported constraints are tokens (protected literal strings), max_lines, and max_characters.
Pixel fitting still belongs to the engine's actual renderer and font checks.

Optional qa_notes maps source IDs to concise notes (1–2000 characters) about concrete ambiguities that could change meaning, gender, perspective or a plot fact.
State what is uncertain and which source evidence needs checking.
These notes reach all three modes as explicitly uncertain context, and appear beside the saved translations for targeted QA.
An unknown speaker alone is not a reason to add a note.
Source review records that the flagged lines were checked; it does not establish a hidden identity.
Intentional ambiguity can remain in a source-checked translation.
Corrections invalidate that review, while retaining the notes and previous result for another pass.

Preserve occurrence identity and scene order.
If an exchange spans requests, include the necessary surrounding source from the same scene/event branch and check continuity at the next review checkpoint.

Compile using compile --input followed by the plan's game-relative path.
The resulting run contains the complete shared system/game instructions, matched glossary and speaker guidance, SFX evidence, field instructions, source context, and advisory reference matches.
API requests also contain the exact provider payload and resolved connection/model settings.
The payload keys a request's lines 1 to N instead of by unit ID, lists speakers and kinds as line ranges, leaves out lines without a speaker, and the reply is mapped back to unit IDs; runs compiled before this keep their unit-ID payloads.
Request size and pricing use the saved model preferences; source content is never silently truncated.

Tracked source files bind to their original-branch blobs so injecting English does not invalidate Japanese source identity.
Other declared inputs bind to bytes.
A changed source version, guidance, reference context or selected scope requires a new plan before new paid work.
Compiler updates can resume saved runs only when rebuilding produces exactly the same logical requests and provider payloads.
Compatibility checks never rewrite saved plans, result identities or spending approvals.
Known provider jobs can still be reconciled against their frozen request set.

## Results and corrections

Inspect a request with request --run ID --index N.
The response includes its fingerprint and any accepted result.
An Agent or reviewed-import receipt contains request_sha256 and translations, where translations is an object with exactly the requested IDs and string values.
Save it in the game workspace and use accept with its relative path.
Missing, duplicate, unexpected or empty outputs and broken declared controls are rejected before acceptance.
So is a translation that fails Guided's content check ([validate_translation_content](../backend/dazedtl/engine/util/translation.py)), such as one collapsed to a mark or its masks, repeating without end or still holding source text, unless it gives the source back unchanged.
So is one that changes its source's backslash control codes or the colour, font and speed scopes they open and close, whether or not its unit lists them, by Guided's control-code check ([runtime_text](../backend/dazedtl/engine/util/runtime_text.py) `validate_unmasked_control_codes`); a code whose argument holds source-language text, such as a ruby, may be translated, except a sound or other asset code, which the game finds by its name.
Saved records are not checked again.
An API run keeps such a line in its source text and accepts the rest of its request, as Guided's Batch keeps it, with the lines it kept named in the request's state ([results.kept](../backend/dazedtl/translation/results.py)); a request with no line that passes is set to failed, as for any rejected result, and nothing is sent again by itself.

For an intentional correction, also supply replaces_sha256 equal to the current result_sha256.
The previous result is archived, the replacement is validated, and affected review/injection/QA is made pending.
An ordinary retry cannot overwrite an accepted translation.
Record source-checked review with review only after performing that review.
Do not regenerate source/review hashes to make stale work count as current.

Accepted records live under .dazedtl/len-method/work/accepted, with correction history beside them.
A result saved by accept records the refusal rules (`refusals.RULES_VERSION`) it was checked under.
A record from other or unrecorded rules is read again under the current ones, and if a line holds a refusal note the request counts as not accepted: results lists its lines as missing and sets an Assistant only run's request back to pending, Progress counts them left, decline accepts it and the next organize sends it again.
Reading never changes the record; the new translation replaces it through accept, which archives it in the correction history.
results --run ID writes the run's accepted translations by line ID to .dazedtl/len-method/work/results/ID.json, with each missing line's request state, and replies with counts only.
It and the progress export give each translation the cleanup Guided gives every line of a reply ([target_text](../backend/dazedtl/engine/util/target_text.py) `translated_line`, corner brackets as quotes by the convertQuotes setting the run froze when it was organized) and then the automatic lint fixes Guided gives a new line ([rpgmaker_qa_lint](../backend/dazedtl/engine/util/rpgmaker_qa_lint.py) `normalize`), on every engine, while the accepted record keeps the translation as accepted; a review of it covers the fixed text.
An export written under older rules (`results.EXPORT_VERSION`) is written again, but only a line whose saved translation changed counts as new, so an applied run does not reopen injection, QA or the patch; its game keeps the earlier text until the run next writes it.
For MV/MZ, operation write_rpgmaker writes the full stops and spacing Guided gives a message into each message and scrolling text it writes ([rpgmaker_blocks](../backend/dazedtl/engine/util/rpgmaker_blocks.py) `written_message`).
It counts translations any run accepted for the same requests, and refuses once the extracted lines it was organized from have changed.
The engine's injector reads that file and keeps its own source-location mappings.
The app's progress export is a derived view, not a replacement for an engine's extraction or injection data.
It lists parts that each hold the lines of 32 requests, and after a saved result the app rebuilds only the parts whose requests or results changed, so the progress counts never wait on every line of a big run.

## Declined requests

In Assistant only, decline --run ID --batch ID --reason TEXT sets aside a request the assistant won't translate, so it carries on with the rest.
The reason is one line of at most 300 characters and never repeats game text.
Decline rather than soften, shorten or leave out lines; a declined request can still be accepted later.
accept refuses a translation that holds a refusal note instead of a line.
Once nothing else in the run is pending, Progress offers the user two ways to finish them: an API estimate compiled from the same plan, which the user approves, or a prompt that has another assistant translate only those requests with request and accept.
Either way the translations land in the same accepted store, so the declined requests then read as accepted, and run --wait on the Assistant only run returns as they are saved.

## API execution and recovery

Only the user approves spending, with the button on the Progress tab, which starts the run.
start resumes only a run the user approved there, and run --wait waits while the estimate waits for that approval.
Each compile or organize replaces the estimate still waiting, so only the newest one can be approved.
When the user switches to another model of the same connection, or between Batch and Live, a waiting quote takes the new prices if every request keeps its text, and Progress shows them; approving it freezes the run again with those settings under the same run ID.
Any other change to API settings or the mode outdates the quote: the user can estimate it again on Progress, which repeats the organize or compile that made it, or you compile and review a new plan.
A quote is an estimate, not a guaranteed bill or an unlimited retry allowance.
It counts input tokens as Guided's estimate does, from the text each request sends, and output as 2.5 times the source payload the model echoes.
New runs include one context-clarification retry for a confirmed provider refusal, with any additional usage billed in the originally selected mode.
Only refused requests are retried; a second refusal stays unresolved.
A note left in place of a line, such as "[Not translated]" or "Translation declined.", is a refusal, never game text.
So is the model talking about its task in a line, such as "I won't produce this content, even in translation." or "Send another batch and I'll continue.", unless the line's source talks about the same thing ([refusals](../backend/dazedtl/translation/refusals.py)).
The rule reads that talk in English and in the target languages written without spaces, Chinese and Japanese, such as 抱歉，我无法翻译这段内容。
Batch clarification jobs retain their own provider IDs and never switch to Live.
Preserve valid authorization on resume when the exact frozen plan and quote still match.

Live and Batch use the same compiled content.
Batch runs retain correlation IDs, provider job IDs, request-level state and receipts.
Pausing stops locally at a checkpoint; it does not cancel a remote job.
Use stop --cancel-provider when the run's `can_cancel_provider` capability allows Batch cancellation; it also cancels the run's clarification Batches.
OpenRouter rejects that operation; ordinary stop pauses local work and prevents later submissions while already submitted jobs continue.
Available completed rows remain recoverable.
See [OpenRouter setup and recovery](user-guide.md#openrouter) for its result-retention limitations.
Record actual token usage separately from the estimate.

An uncertain request is never sent again automatically.
Attach a matching Batch job with attach-batch; unrelated or incomplete request IDs keep the run blocked.
For an uncertain Live call, check the provider first, then resolve-uncertain --retry-reviewed permits a new remaining-work quote.
It does not issue a retry itself.
The Guided UI also permits a separately estimated and approved new translation regardless of older run status, with an advisory about possible duplicate charges.
This does not authorize automatic retries or settle the older receipts.

## Delivery and future versions

Use the maintained progress report format right after the first state read, after saved milestones and before waits or handoff.
Reports are accepted while an API run is active, and refused only while an operation changes the game.
Starting or resuming an API run clears the blocker the last report named, since the run answers it; a blocker reported during the run stays until a later report clears it.
Counts describe saved units; extraction coverage, review, images, injection, runtime QA and packaging are separate evidence.
Report declined lines, set-aside counts and unresolved extraction explicitly.
A complete text count cannot complete QA.

Save the measured Line widths with line_widths, then stage MV/MZ JSON and use write_rpgmaker so the existing writer preserves _original and fits the text to them.
Saving widths again fits the text the writer already wrote to the new ones and lists what a fixed window still cuts off.
When an official source version changes, rebase_rpgmaker additionally requires the expected original commit and source bytes identical to that original-branch file.
It rebuilds metadata from that trusted source and retains Git history.
Native formats use their existing source/injection sidecars and verified native reconstruction.

Every change DazedTL makes to the game, through these operations or the app, is its own checkpoint: one commit on the translation branch whose subject names its stage and what it did ([architecture](architecture.md#checkpoints)).
The app also checkpoints the assistant's work itself: each progress report saves what waits in the patch, the assistant's own edits included, as a checkpoint of the phase the last report named, such as `Assistant-led: Injection`, and so does the end of each translation run, when it finishes, stops or fails.
write_rpgmaker and rebase_rpgmaker, which an assistant runs once per file, wait for that phase checkpoint instead of each being one; any other change DazedTL makes first saves them as their phase's.
Undoing a phase's checkpoint under Checkpoints, or going back past it, reopens that phase and every later one in the last report, and a game update reopens extraction and every later phase, since the new version's text is counted and extracted again ([progress_report](../backend/dazedtl/translation/progress_report.py)).
These checkpoints let the files the runtime manifest Git setup registered lists into the patch.
Changes made to the game outside DazedTL are saved as a checkpoint of their own before the next other change DazedTL makes, a package or a game update's preview.
The checkpoint operation is kept for assistants started before then: it saves what waits in the patch as one checkpoint, with its `message` as the summary when given, and files its optional runtime `manifest` lists that the patch lacks join the patch.
A file outside the patch takes its original bytes from the `original` branch or the game's record of its original files, so a checkpoint reads no backup.
Do not create parallel full workspace copies or checkpoint ZIPs.
Routine progress reports remain lightweight.
DazedTL takes no new backups; older ones are preserved, with no automatic cleanup or conversion.
Use backups to list them, including older profile backups. restore_backup takes backup_id and destination, which must name a new directory outside the game.
It verifies content and never overwrites existing files.
write_rpgmaker's `backup_id` names a saved original to read its source path from: a commit of `refs/dazedtl/originals` or an older backup.
Standalone recovery without an app profile is documented in the [user guide](user-guide.md#backups-from-before-checkpoints).
Package requires current reported QA for the runtime manifest Git setup or the last checkpoint named, saves outstanding changes, and creates a local patch from the files the translation branch tracks.
It does not create remotes, push, or upload.
Writing the game's complete `gameupdate/patch-config.txt` saves it with the patch, so manifests need not list it; every release ZIP, Guided's or Assistant-led's, clean game or patch, leaves it out unless the commit is the verified public version, which it then stamps ([release.public_version](../backend/dazedtl/translation/release.py)).
Every checkpoint, package and QA record also carries DazedTL's other files the game holds, so manifests need not list them either: GameUpdate's launchers and scripts, the update check and Forge plugins Set up installs, and the playtest's fixes plugin with the `js/main.js` that loads it.
A package refuses a `plugins.js` that switches on a plugin whose file neither the patch nor the original game holds, naming the plugin, since players' game would stop at start; the original game's plugins are those its Git records or an older prepared backup list, never DazedTL's own.
TL Inspector stays on the translator's computer: its file holds their editor command, so no patch carries it and `plugins.js` never lists it; the update check loads it where its file is, so installing or removing it makes no checkpoint of its own, once the game's update check is current.
Older installs listed it, so opening such a game whose Git is set up takes it out of `plugins.js` as one checkpoint, and a package that still lists it, or holds its file, is refused.
It likewise refuses a `js/main.js` that loads the playtest's fixes the patch lacks, or fixes no `js/main.js` in the patch loads; without a recorded or Git copy, the original of the `js/main.js` loading the fixes is that file without the loading line.

For an official update, stage_update records the new release's files in the game's Git and creates a separate working copy.
A folder holding fewer than half of the game's files is staged as a patch unless `patch` says otherwise, and version_preview then compares a staged release only as what it was staged as.
Complete the relevant engine preparation there, then use version_preview and version_apply with its saved preview ID.
Continue/abort operate on the preserved Git recovery state.
After a completed update, version_handoff returns the task **Copy post-update task** copies: the starting prompt's own steps from census on, in the project's mode and language pair.
Reuse unchanged translations with their source/context evidence; never rely on array positions alone across versions.
