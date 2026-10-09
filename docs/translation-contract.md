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
Continuation validates findings, prepares scoped working copies and returns the next request, for whatever is left, to the same agent session until every plugin file is done.
Saved progress appears through the app observer.
The helper cannot publish plugin files; final runtime Apply stays in the app.
Read the active request before resuming after a lost reply.

An Assistant-led project that includes image text runs the Images steps with `images --scan`, `--investigate`, `--translate` and `--apply`; `images --status` names the next one.
Investigate and Translate save the same request-bound tasks Guided's Images task hands out, as files to follow, and the next step reads their saved reports.
The assistant also does the user's part: its recommendations stay the list, and Apply publishes the translated, reviewed images and returns the runtime files to add to the patch manifest.
The app turns the Image Manager's list into the image records that progress reports and packaging count.
An image in the list counts until it is applied, one its translation skipped drops out, and the records complete once every image has a finding.
Images is its own progress phase; a report that leaves it out gets it from these records, complete once they are and active once they list an image.
Guided projects keep these steps in their Images task.

### Sandboxed connections

A network sandbox can block loopback even when DazedTL is running.
The generated starting prompt includes the permission and recovery procedure; the helper repeats it on connection failures.
Use the assistant's normal permission flow for the helper and verify access with the read-only `state` command before diagnosing an app outage.
A lost response may follow a completed action, so inspect saved state and runs before retrying a mutation or paid submission.

### Saved state and setup

Use state before starting.
Every Assistant-led helper call also records when the assistant last reached the project, which Progress shows before its first report.
Starting a project over is the user's choice in the app; the helper cannot.
It reports the portable options, current Git and backup state, saved progress, pending drafts, frozen runs, and any saved phased run requiring recovery.
Record the detected engine with identify and a project-relative investigation report.
Operation commands return saved job IDs; inspect them with run until they complete, fail, stop, or await approval or provider results.
`run --wait MINUTES` waits in one command and returns as soon as the run's state changes, so a long Batch costs the assistant one turn per wait instead of one per poll.

Source backup precedes runtime preparation.
RPG Maker preparation uses the existing shared helper; Ace and other formats require their engine's extraction/conversion route first.
Git setup requires a source version and a reviewed runtime manifest for a fresh baseline.
The untranslated flag is an attestation after source inspection, not permission to label English as an original.

## Source units

Len's extractor saves every line in scope as source units, and organize turns them into requests, so the assistant never reads or rewrites the game's text to group it.
Use units-format for an example.
The authoritative validator and grouping are in [organize.py](../backend/dazedtl/translation/organize.py).
The file is an object with version 1 and units, a list in play order; each unit has these fields:

| Field | Contract |
| --- | --- |
| id | Required. Unique single-line text of at most 240 characters that the engine's injector maps back to its location. |
| scene | Required. The engine's scene, such as an event page, common event, scenario label or table. A scene's units stay together. |
| source | Required. The Japanese line exactly as the injector will replace it. |
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
A request holding several scenes names which lines belong to each, so the model keeps their speakers and context apart.
A larger scene splits into even parts, each carrying the scene's earlier lines as source context.
Each request takes its first unit's ID, and the plan is saved under .dazedtl/len-method/work/plans by its content, then compiled.
The reply holds counts only; errors name unit IDs without repeating game text.
Move game text only with scripts, never by pasting or retyping it.

## Census and scope

Scope is mechanical: DazedTL counts the original game's Japanese text itself, and the assistant never decides what is in scope.
The census helper command runs an operation that reads the prepared source backup, never the working copy, and saves its count in the profile.
The authoritative readers, rules and coverage are in [census.py](../backend/dazedtl/translation/census.py).
It reads RPG Maker MV/MZ JSON and plugins, JavaScript, KAG/Tyrano and Ren'Py scripts, decompiled YU-RIS scripts, HTML, text and YAML.
It opens RGSS archives and XP/VX/Ace data, Electron asar and unencrypted xp3 archives, and Wolf data through the bundled WolfDawn.
It reads YU-RIS archive indexes, so only archives holding scripts or text need a decoded dump.
For containers it can't open, such as Unity, Unreal or encrypted archives, census --decoded reads a game-relative folder that Len's decoder wrote, and Progress says the count came from it.

Each counted string has a kind and a field naming its structure, never a map, event or scene.
Coverage counts Japanese runs by occurrence: each must appear in a unit, which holds the game's text exactly, be a term of the game's own glossary, or be set aside by a rule.
Built-in rules set aside text players never see, such as comments, labels, asset names, switch names and the readmes beside a game; mod loaders and runtimes installed beside it, such as BepInEx, are not read.
Comma or tab separated text is read by column; a table translating its Japanese first column into another language names that column table:key, and a built-in rule sets aside a Chinese column, whose characters Japanese runs can't tell apart.
The assistant can add rules in .dazedtl/len-method/work/scope-rules.json, as version 1 with rules of kind, field and reason (asset_name, identifier, comment, script_code, not_displayed or other_language), each optionally limited by file, a path pattern, or values, exact runs such as a script format's Japanese command words.
Rules work on every kind, including decoded dumps, generic JSON and plain text, and never set aside dialogue, choices, names or other text the player reads in formats DazedTL reads itself.
organize --complete is refused without a current census, while archives still need a decoded dump, or while anything is uncovered; .dazedtl/len-method/work/census-uncovered.json lists each uncovered location.
Rules apply before extraction, so an identifier a rule sets aside never uses up the unit for the same words where the player reads them.
Content is never a reason to leave text out; the assistant declines a request it won't translate, which keeps its lines in scope.

## Source plan

Organize writes this plan; a plan written by hand compiles the same way, and plan-format shows a minimal one.
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

For an intentional correction, also supply replaces_sha256 equal to the current result_sha256.
The previous result is archived, the replacement is validated, and affected review/injection/QA is made pending.
An ordinary retry cannot overwrite an accepted translation.
Record source-checked review with review only after performing that review.
Do not regenerate source/review hashes to make stale work count as current.

Accepted records live under .dazedtl/len-method/work/accepted, with correction history beside them.
results --run ID writes the run's accepted translations by line ID to .dazedtl/len-method/work/results/ID.json, with each missing line's request state, and replies with counts only.
It counts translations any run accepted for the same requests, and refuses once the extracted lines it was organized from have changed.
The engine's injector reads that file and keeps its own source-location mappings.
The app's progress export is a derived view, not a replacement for an engine's extraction or injection data.

## Declined requests

In Assistant only, decline --run ID --batch ID --reason TEXT sets aside a request the assistant won't translate, so it carries on with the rest.
The reason is one line of at most 300 characters and never repeats game text.
Decline rather than soften, shorten or leave out lines; a declined request can still be accepted later.
Once nothing else in the run is pending, Progress offers the user two ways to finish them: an API estimate compiled from the same plan, which the user approves, or a prompt that has another assistant translate only those requests with request and accept.
Either way the translations land in the same accepted store, so the declined requests then read as accepted, and run --wait on the Assistant only run returns as they are saved.

## API execution and recovery

Review the run's complete request set and quote before start --approve TOKEN.
This is the spending decision inside the same assistant conversation or app run.
The user can instead approve the quote on the Progress tab, which starts the run without the assistant; inspect the run before starting it.
A quote stops being approvable once API settings or the translation mode change after it; start refuses it, so compile and review a new plan.
A quote is an estimate, not a guaranteed bill or an unlimited retry allowance.
New runs include one context-clarification retry for a confirmed provider refusal, with any additional usage billed in the originally selected mode.
Only refused requests are retried; a second refusal stays unresolved.
Batch clarification jobs retain their own provider IDs and never switch to Live.
Preserve valid authorization on resume when the exact frozen plan and quote still match.

Live and Batch use the same compiled content.
Batch runs retain correlation IDs, provider job IDs, request-level state and receipts.
Pausing stops locally at a checkpoint; it does not cancel a remote job.
Use stop --cancel-provider when the run's `can_cancel_provider` capability allows Batch cancellation.
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

Stage MV/MZ JSON and use write_rpgmaker so the existing writer preserves _original.
When an official source version changes, rebase_rpgmaker additionally requires the expected original commit and source bytes identical to that original-branch file.
It rebuilds metadata from that trusted source and retains Git history.
Native formats use their existing source/injection sidecars and verified native reconstruction.

Checkpoint uses the full reviewed runtime manifest, aligns original and the translation branch, and snapshots the ignored workspace in .dazedtl/backups/v2.
Source, prepared-source and workspace snapshots reuse identical file content.
The backup store never includes itself; an unchanged snapshot reuses its ID.
Use backup_workspace for a recovery milestone without a patch commit.
Do not create parallel full workspace copies or checkpoint ZIPs.
Routine progress reports remain lightweight.
Preserve older backups; no automatic cleanup or conversion is performed.
The backup result reports bytes_total, bytes_added, bytes_reused and reused_snapshot.
Packaging reuses matching saved content.
Use backups to list local restore points and older profile backups. restore_backup takes backup_id and destination, which must name a new directory outside the game.
It verifies content and never overwrites existing files.
Snapshot IDs remain valid after moving the entire store with the game; engine source readers use temporary verified materialization.
Standalone recovery without an app profile is documented in the [user guide](user-guide.md#backups-and-recovery).
Package requires current reported QA and creates a local patch from reviewed Git files.
It does not create remotes, push, or upload.
The existing GameUpdate checks govern public commit stamping.

For an official update, stage_update preserves the new original and creates a separate working copy.
Complete the relevant engine preparation there, then use version_preview and version_apply with its saved preview ID.
Continue/abort operate on the preserved Git recovery state.
After a completed update, version_handoff supplies the shared follow-up instructions.
Reuse unchanged translations with their source/context evidence; never rely on array positions alone across versions.
