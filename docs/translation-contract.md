# Translation adapter contract

This is the interface for engine adapters and the assistant receiving the starting prompt.
Len's maintained skill and its engine references remain the source of translation methodology.
The app supplies the invocation, project ID and workspace path; no API credentials belong in adapter files or prompts.

## Project helper

Keep the app open and use the generated command prefix with scripts/project.py.
Its --help and operation --help describe available commands and operation arguments.
The helper talks only to the profile's authenticated loopback endpoint and does not use a proxy or follow redirects.
After reopening the app, the same invocation reads the new connection descriptor and resumes saved state.

The single plugin task uses `plugins` to read its active request and
`plugins --continue-request ID` after saving each request-bound report. Continuation validates
findings, prepares scoped working copies and returns the next stage's instructions to the same
agent session. Saved progress appears through the app observer. The helper cannot publish plugin
files; final runtime Apply stays in the app. Read the active request before resuming after a lost reply.

### Sandboxed connections

A network sandbox can block loopback even when DazedTL is running. The generated starting prompt
includes the permission and recovery procedure; the helper repeats it on connection failures.
Use the assistant's normal permission flow for the helper and verify access with the read-only `state`
command before diagnosing an app outage. A lost response may follow a completed action, so inspect
saved state and runs before retrying a mutation or paid submission.

### Saved state and setup

Use state before starting. It reports the portable options, current Git and backup state, saved progress,
pending drafts, frozen runs, and any saved phased run requiring recovery.
Record the detected engine with identify and a project-relative investigation report.
Operation commands return saved job IDs; inspect them with run until they finish or need attention.

Source backup precedes runtime preparation. RPG Maker preparation uses the existing shared helper;
Ace and other formats require their engine's extraction/conversion route first.
Git setup requires a source version and a reviewed runtime manifest for a fresh baseline.
The untranslated flag is an attestation after source inspection, not permission to label English as an original.

## Source plan

Use plan-format for a minimal example. The authoritative validator is
[requests.py](../backend/dazedtl/translation/requests.py).
The JSON object has these fields:

| Field | Contract |
| --- | --- |
| version | 2 for new source plans. Existing saved runs with unversioned inputs remain readable and can resume when their frozen requests are unchanged. |
| complete | True only when the selected scope's entire planned corpus has been independently audited. API quoting requires this. |
| inputs | Unique project-relative source and guidance files. Use immutable source exports, not a store whose translation columns will change. |
| batches | Ordered coherent batches, each with a stable unique id and an ID-to-Japanese sources object. |

Every batch requires kinds and speakers, both with exactly the same IDs as sources.
Classify each line as dialogue, narration, ui, or unknown when its text type is unresolved.
Use an evidenced speaker name or null for unknown/inapplicable speakers; UI must use null.
Narration may carry a known narrator's identity without turning it into spoken dialogue.
Unknown speakers are valid and never generate review flags automatically. Do not inherit the previous speaker
or infer identity/gender from speech style. Resolve subjects and addressees independently using the Japanese.

A batch can also have source_context for preceding Japanese; scene_context for evidence-based scene and runtime-substitution notes;
an instruction_key from the existing field templates; and constraints keyed by source ID.
Supported constraints are tokens (protected literal strings), max_lines, and max_characters.
Pixel fitting still belongs to the engine's actual renderer and font checks.

Optional qa_notes maps source IDs to concise notes (1–2000 characters) about concrete ambiguities
that could change meaning, gender, perspective or a plot fact. State what is uncertain and which source evidence needs checking.
These notes reach all three modes as explicitly uncertain context, and appear beside the saved translations for targeted QA.
An unknown speaker alone is not a reason to add a note. Source review records that the flagged lines were checked;
it does not establish a hidden identity. Intentional ambiguity can remain in a source-checked translation.
Corrections invalidate that review, while retaining the notes and previous result for another pass.

Preserve occurrence identity and scene order. Do not deduplicate dialogue globally by Japanese text.
Keep nameplate text separate from contextual speaker labels. If an exchange spans requests,
include the necessary surrounding source from the same scene/event branch and check continuity at the next review checkpoint.

Compile using compile --input followed by the plan's game-relative path.
The resulting run contains the complete shared system/game instructions, matched glossary and speaker guidance,
SFX evidence, field instructions, source context, and advisory reference matches.
API requests also contain the exact provider payload and resolved connection/model settings.
Request size and pricing use the saved model preferences; source content is never silently truncated.

Tracked source files bind to their original-branch blobs so injecting English does not invalidate Japanese source identity.
Other declared inputs bind to bytes. A changed source version, guidance, reference context or selected scope requires a new plan before new paid work.
Compiler updates can resume saved runs only when rebuilding produces exactly the same logical requests and provider payloads.
Compatibility checks never rewrite saved plans, result identities or spending approvals.
Known provider jobs can still be reconciled against their frozen request set.

## Results and corrections

Inspect a request with request --run ID --index N. The response includes its fingerprint and any accepted result.
An Agent or reviewed-import receipt contains request_sha256 and translations, where translations is an object
with exactly the requested IDs and string values. Save it in the game workspace and use accept with its relative path.
Missing, duplicate, unexpected or empty outputs and broken declared controls are rejected before acceptance.

For an intentional correction, also supply replaces_sha256 equal to the current result_sha256.
The previous result is archived, the replacement is validated, and affected review/injection/QA is made pending.
An ordinary retry cannot overwrite an accepted translation. Record source-checked review with review only after performing that review.
Do not regenerate source/review hashes to make stale work count as current.

Accepted records live under .dazedtl/len-method/work/accepted, with correction history beside them.
Adapters should import those accepted ID mappings into their existing source/translation stores and retain their source-location mappings.
The app's progress export is a derived view, not a replacement for an engine's extraction or injection data.

## API execution and recovery

Review the run's complete request set and quote before start --approve TOKEN.
This is the spending decision inside the same assistant conversation or app run.
A quote is an estimate, not a guaranteed bill or an unlimited retry allowance.
New runs include one context-clarification retry for a confirmed provider refusal, with any additional
usage billed in the originally selected mode. Only refused requests are retried; a second refusal stays
unresolved. Batch clarification jobs retain their own provider IDs and never switch to Live.
Preserve valid authorization on resume when the exact frozen plan and quote still match.

Live and Batch use the same compiled content. Batch runs retain correlation IDs, provider job IDs,
request-level state and receipts. Pausing stops locally at a checkpoint; it does not cancel a remote job.
Use stop --cancel-provider to request Batch cancellation. Available completed rows remain recoverable.
Record actual token usage separately from the estimate.

An uncertain request is never sent again automatically. Attach a matching Batch job with attach-batch;
unrelated or incomplete request IDs keep the run blocked. For an uncertain Live call, check the provider first,
then resolve-uncertain --retry-reviewed permits a new remaining-work quote. It does not issue a retry itself.
The Guided UI also permits a separately estimated and approved new translation regardless of older run status, with an advisory about possible duplicate charges. This does not authorize automatic retries or settle the older receipts.

## Delivery and future versions

Use the maintained progress report format after saved milestones and before waits or handoff.
Counts describe saved units; extraction coverage, review, images, injection, runtime QA and packaging are separate evidence.
Report unresolved and excluded material explicitly. A complete text count cannot complete QA.

Stage MV/MZ JSON and use write_rpgmaker so the existing writer preserves _original.
When an official source version changes, rebase_rpgmaker additionally requires the expected original commit
and source bytes identical to that original-branch file. It rebuilds metadata from that trusted source and retains Git history.
Native formats use their existing source/injection sidecars and verified native reconstruction.

Checkpoint uses the full reviewed runtime manifest, aligns original and the translation branch, and snapshots the ignored workspace in .dazedtl/backups/v2.
Source, prepared-source and workspace snapshots reuse identical file content. The backup store never includes itself; an unchanged snapshot reuses its ID.
Use backup_workspace for a recovery milestone without a patch commit. Do not create parallel full workspace copies or checkpoint ZIPs.
Routine progress reports remain lightweight. Preserve older backups; no automatic cleanup or conversion is performed.
The backup result reports bytes_total, bytes_added, bytes_reused and reused_snapshot. Packaging reuses matching saved content.
Use backups to list local restore points and older profile backups. restore_backup takes backup_id and destination,
which must name a new directory outside the game. It verifies content and never overwrites existing files.
Snapshot IDs remain valid after moving the entire store with the game; engine source readers use temporary verified materialization.
Standalone recovery without an app profile is documented in README.
Package requires current reported QA and creates a local patch from reviewed Git files.
It does not create remotes, push, or upload. The existing GameUpdate checks govern public commit stamping.

For an official update, stage_update preserves the new original and creates a separate working copy.
Complete the relevant engine preparation there, then use version_preview and version_apply with its saved preview ID.
Continue/abort operate on the preserved Git recovery state. After a completed update, version_handoff supplies the shared follow-up instructions.
Reuse unchanged translations with their source/context evidence; never rely on array positions alone across versions.
