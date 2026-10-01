# Translation adapter contract

This is the interface for engine adapters and the assistant receiving the starting prompt.
Len's maintained skill and its engine references remain the source of translation methodology.
The app supplies the invocation, project ID and workspace path; no API credentials belong in adapter files or prompts.

## Project helper

Keep the app open and use the generated command prefix with scripts/project.py.
Its --help and operation --help describe available commands and operation arguments.
The helper talks only to the profile's authenticated loopback endpoint and does not use a proxy or follow redirects.
After reopening the app, the same invocation reads the new connection descriptor and resumes saved state.

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
| complete | True only when the selected scope's entire planned corpus has been independently audited. API quoting requires this. |
| inputs | Unique project-relative source and guidance files. Use immutable source exports, not a store whose translation columns will change. |
| batches | Ordered coherent batches, each with a stable unique id and an ID-to-Japanese sources object. |

A batch can also have speakers with exactly the same source IDs and null for unknown speakers;
source_context for preceding Japanese; scene_context for evidence-based scene and runtime-substitution notes;
an instruction_key from the existing field templates; and constraints keyed by source ID.
Supported constraints are tokens (protected literal strings), max_lines, and max_characters.
Pixel fitting still belongs to the engine's actual renderer and font checks.

Preserve occurrence identity and scene order. Do not deduplicate dialogue globally by Japanese text.
Keep nameplate text separate from contextual speaker labels. If an exchange spans requests,
include the necessary surrounding source and check continuity at the next review checkpoint.

Compile using compile --input followed by the plan's game-relative path.
The resulting run contains the complete shared system/game instructions, matched glossary and speaker guidance,
SFX evidence, field instructions, source context, and advisory reference matches.
API requests also contain the exact provider payload and resolved connection/model settings.
Request size and pricing use the saved model preferences; source content is never silently truncated.

Tracked source files bind to their original-branch blobs so injecting English does not invalidate Japanese source identity.
Other declared inputs bind to bytes. A changed source version, guidance, reference context, compiler or selected scope requires a new plan before new paid work.
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
Preserve valid authorization on resume when the exact frozen plan and quote still match.

Live and Batch use the same compiled content. Batch runs retain correlation IDs, provider job IDs,
request-level state and receipts. Pausing stops locally at a checkpoint; it does not cancel a remote job.
Use stop --cancel-provider to request Batch cancellation. Available completed rows remain recoverable.
Record actual token usage separately from the estimate.

An uncertain request is never sent again automatically. Attach a matching Batch job with attach-batch;
unrelated or incomplete request IDs keep the run blocked. For an uncertain Live call, check the provider first,
then resolve-uncertain --retry-reviewed permits a new remaining-work quote. It does not issue a retry itself.
Use the saved phased-run recovery path for an existing legacy run before creating overlapping new work.

## Delivery and future versions

Use the maintained progress report format after saved milestones and before waits or handoff.
Counts describe saved units; extraction coverage, review, images, injection, runtime QA and packaging are separate evidence.
Report unresolved and excluded material explicitly. A complete text count cannot complete QA.

Stage MV/MZ JSON and use write_rpgmaker so the existing writer preserves _original.
When an official source version changes, rebase_rpgmaker additionally requires the expected original commit
and source bytes identical to that original-branch file. It rebuilds metadata from that trusted source and retains Git history.
Native formats use their existing source/injection sidecars and verified native reconstruction.

Checkpoint uses the full reviewed runtime manifest, aligns original and the translation branch, and backs up the ignored workspace separately.
Package requires current reported QA and creates a local patch from reviewed Git files.
It does not create remotes, push, or upload. The existing GameUpdate checks govern public commit stamping.

For an official update, stage_update preserves the new original and creates a separate working copy.
Complete the relevant engine preparation there, then use version_preview and version_apply with its saved preview ID.
Continue/abort operate on the preserved Git recovery state. After a completed update, version_handoff supplies the shared follow-up instructions.
Reuse unchanged translations with their source/context evidence; never rely on array positions alone across versions.
