# Architecture

## Ownership

| Location | Responsibility |
| --- | --- |
| [app/src/app](../app/src/app) | Shell, navigation, and the single application/job observer |
| [app/src/features](../app/src/features) | Each feature's components, hooks, and styles |
| [app/src/ui](../app/src/ui), [styles](../app/src/styles) | Shared presentation, design tokens, and layout |
| [app/src/state](../app/src/state) | Action feedback, serialized drafts, and leave guards |
| [app/src/api](../app/src/api) | Typed contracts, transport, and named application operations |
| [app/electron](../app/electron) | Native dialogs, approved folder opening, close handshake, Python process and update controller |
| [backend/dazedtl](../backend/dazedtl) | Project identity, settings, workflow actions, and run ownership |
| [compatibility](../backend/dazedtl/compatibility) | The only boundary allowed to import the bundled engine |
| [engine](../backend/dazedtl/engine) | Preserved parsers, worker implementation, native tools and translation toolkit |

The shell composes features; features use shared services without importing each other's internals.
Shared UI components do not import features or call the backend.
The renderer is sandboxed and has no direct filesystem, process, or network access.
The Qt GUI from `DazedMTLTool` is the reference for guided workflow ordering and behavior; its retired Electron interface is not a UX reference.
The Translation service owns project operations, request plans, accepted results, and run recovery for both the UI and the external agent helper.
Len's maintained skills own engine investigation and methodology; the compatibility layer supplies the existing context, Git, preparation, injection, and provider helpers.
The preserved runner continues to own parsing, speaker preparation, phase profiles, glossary collection and Batch receipts.
App workers own source backup, Git baselines, checkpoints and local patch packaging for both approaches.
The Translation workspace composes file selection, preferences and the preserved phased runner.
Its [workspace hook](../app/src/features/guided/workspace/useGuidedWorkspace.tsx) owns shared state, navigation and action review; each task's body and footer controls come from its [task view](../app/src/features/guided/workspace/tasks/index.ts), with sheets and dialogs as separate components.
Its backend, [Guided](../backend/dazedtl/translation/guided.py), composes collaborators for [action review and execution](../backend/dazedtl/translation/guided_actions.py), [run inspection](../backend/dazedtl/translation/guided_inspection.py), the [release form](../backend/dazedtl/translation/guided_release.py) and [context setup](../backend/dazedtl/translation/guided_context.py).
Working-copy ownership and resync behavior are described under [Workflow and shared presentation](#workflow-and-shared-presentation).

## Engine and resources

The adapter retains existing engine behavior while capabilities are extracted incrementally.
Neither checkout is a runtime dependency.
The [runtime locator](../backend/dazedtl/compatibility/runtime.py) selects the engine shipped inside this package in the app, workers and standalone helpers, independently of cwd and old engine environment variables.
There is no external-engine fallback.
The runtime was imported from `b91bede18fd2bbd5a9b99f1a866f061bc13865c1` with its [license](../backend/dazedtl/engine/LICENSE.md) and component notices.
Saved manual runs record the [engine version](../backend/dazedtl/engine/desktop/backend/manual.py) that prepared them and resume only on that version; plans from before explicit versions match by their recorded byte hash.
Raise the version when a change would make a resumed run build requests or parse files differently.
Their historical Python namespaces are internal to the compatibility boundary; the old UI and application server are not shipped.
The compatibility layer extends engine behavior only through declared [extension points](../backend/dazedtl/engine/util/extensions.py) and engine settings, never by replacing engine functions.
Every import alias shares a point's dispatcher, and reconfiguring a named layer replaces it in place.
Mark an engine function as a point where DazedTL needs to extend it, rather than wrapping it from outside.
The base translation rules in [system.md](../backend/dazedtl/engine/data/skills/system.md), the shared prompt templates, field instructions, base glossary and SFX reference live in the engine's [data](../backend/dazedtl/engine/data) directory.
The base prompt bounds localization to supplied source text to preserve its register without inviting new scene content or assistant responses in game dialogue.
Existing workspace `engine/shared-data` overrides retain precedence and native path validation.
Resources are not seeded into profiles, so future default changes reach new preparations without overwriting customizations.
Frozen run context stays authoritative for execution and recovery.
Engine parsers, context assembly and Len's maintained methodology/tool bundle are shipped in the owned engine behind the compatibility boundary.
Existing phased jobs retain their original engine-owned records and recovery path rather than being rewritten into a different request format.

## Guided runs and paid work

### Estimates and approval

Guided main text shares configuration while retaining independent database and event selections.
Each phase binds its estimate to source, scope, provider and pricing, guidance, and layout.
New estimate and Batch preparation workspaces are temporary until approval; they do not enter saved history or contribute translated outputs.
Each Translate click discards that phase’s unapproved preparation and creates a fresh estimate.
Decline discards new unapproved work after its worker exits, and restart removes abandoned temporary work.
Approved work is retained before signaling the worker, including separately approved speaker translation.
Existing historical runs remain intact.
Paid review requires that matching estimate and rechecks it before the one-use submission.
Cost dialogs focus on price, selected scope and approval; an optional Preview request opens the existing prepared text, context and exact payload without preparing or submitting work.
Preview request shows requests an estimate kept: estimates keep them on connections that support Batch, while Live-only connections estimate from token counts and offer no preview; Batch review previews its collected requests.
Closing the preview returns to the same approval.
Speaker interpretation stays with the user.
Translate keeps its game text tasks below the shared phase navigation: Database files, Maps & events (including CommonEvents and Troops), and Other event text.
Task completion aggregates verified per-file progress across runs through [translationTaskComplete](../app/src/features/guided/translationView.ts), so re-running some files keeps the rest: Database files and Maps & events over their full file groups, independent of checkbox selection, and event codes and comparisons over the selected event files plus every file an earlier run of that step included, so clearing the selection keeps finished work.
Each file's current owning run must retain complete output or explicit evidence that no requests were needed; active work, partial or missing output, changed sources and retired runs cannot establish completion.
Current findings reviewed with no source enabled complete Other event text without a run, since nothing in it needs translating.
Translate is complete only when all its tasks are complete; action and cost reviews remain bound to the selected scope.
Translate starts a local estimate and follows that exact job once into Live review or local Batch preparation.
Failed, stopped and stale estimates stop preparation with feedback.
An explicit zero-request estimate opens a result explaining that no new API work was needed; absent saved request payloads never imply zero work.
Stop translation is available for Live execution.
Batch work keeps monitoring automatically; Run history opens its progress and controls.
Navigation never submits work.
App restarts can continue the unchanged approved queue and its saved clarification allowance.
Legacy estimate continuation records remain readable for recovery.
Each pending Batch or speaker approval opens once in a focused cost review with visible token counts, mode-specific pricing, prepared file scope and an explicit Decline action.
Cost comparisons use plain labels for totals without prompt caching and with estimated prompt caching, explain reuse of repeated instructions, and include cache creation without promising savings.
The [Batch pricing adapter](../backend/dazedtl/compatibility/batch_pricing.py) calculates new GPT-6.1 Sol cached quotes from native token counts and frozen input/output rates using its [documented cache rates](https://developers.openai.com/api/docs/models/gpt-6.1-sol); saved historical estimates remain unchanged.
Inspection leaves Review cost available, while Translate always prepares again.
Approval rechecks the temporary preparation’s current inputs before the native one-use approval controls submission.
Once approved, the frozen request remains authoritative for recovery and is never silently rebuilt.
The fresh Batch speaker check validates unresolved nameplates against frozen files and the current glossary before collection; it retains its separate approval if translation is needed.
Nameplates may contain character names or other display labels, so the review does not assume a character identity.
This small preparation uses Live pricing to avoid waiting for a separate name Batch, and the review distinguishes it from the selected Batch mode for file text.
The file-text Batch receives its own cost review after names are resolved.
The [name-result adapter](../backend/dazedtl/compatibility/speaker_results.py) retains the native save outcome and a verified glossary snapshot independently of the later Batch decision.
The shared observer exposes pending, saved and unavailable outcomes; Batch review and the request inspector’s Technical tab show the result with bounded, read-only translation inspection.
Name feedback is a compact secondary note below the reviewed cost and file scope, or beneath the active preparation status, with its inspection action adjacent.
Approval alone never establishes success.
Declining or stopping the file Batch keeps approved names reusable in the next run’s frozen glossary, with current glossary entries and aliases taking precedence.
Reuse is bound to the project, target language and source pass, participates in estimate identity, and preserves the shared guidance and drafts.
Older runs can recover exact entries only from retained approved names, native save evidence and that run’s glossary.
Closing preparation after approving names preserves the paid run.
Read-only provider details resolve the submitted connection from canonical settings by its recorded runtime name, endpoint and organization, regardless of the active account.
Provider monitoring and new runs have independent isolated workers.
Cost approval checks its own frozen preparation and one-use token under the API lock; other runs cannot revoke it.
Existing Live resumes retain their frozen settings and require explicit review; Batch recovery follows saved provider receipts and the frozen clarification allowance described above.
New remaining work requires a fresh estimate and spending review.
The compact footer keeps Translate and available Apply actions beside the selected scope.
Translate immediately opens one stable estimate dialog; preparation, cost approval, no-work results and actionable failures stay inside it.
An estimate without work is a result, not a preparation to cancel.
Batch estimates count no requests; Live estimates report no request count, so they qualify only by finding no source text.
Then each selected file with no text left to translate shows Complete for that phase until a newer attempt includes it or a resync replaces it, and Close only closes.
Text reused from earlier responses still needs a run to write it, so it never completes a file this way.
The existing observer advances only that dialog’s owned estimate, and a canceled late reply cannot open a review or start paid work.
Saved active runs do not disable Translate or lock its file selection and mode; only the current preparation/action owns pending feedback.
Selecting more files or clicking Translate again retains the engine’s skip-translated behavior.
Apply includes only checked files with saved output in the current task, including output from earlier runs.
Model and method live in the toolbar.
Resync, labelled Reload from game, sits beside file selection apart from its selection helpers; Options edits translation behavior and opens saved translations; wrapping limits belong to the layout workflow.
Live file rows count returned requests, including rejected attempts; native map-command totals are not used as translation percentages.
Finished Live runs clear progress and preparation labels.
Batch rows use provider request receipts.
The request inspector reconciles the selected run against the shared observer and reloads a selected response when its receipt state changes, without adding a polling loop.

### Frozen request policies

New API runs freeze a provider-default generation policy before estimation and review.
The compatibility adapter omits the native engine's implicit temperature, frequency penalty, and reasoning effort; current model preferences expose no explicit overrides for these parameters.
The policy participates in estimate identity and applies to both Live and Batch request construction.
Saved runs without this policy retain their original parameters and recovery behavior.
New API runs also freeze a [single clarification retry](../backend/dazedtl/translation/refusals.py) for provider refusals.
The clarification identifies the existing fictional source and the owner's adult-character statement without changing source facts or asking the provider to disregard its rules.
Live retains both attempts and their usage; Batch submits only refused rows through the same Batch provider and retains successful originals.
The [retry journal](../backend/dazedtl/translation/batch_refusals.py) records intent before submission and saves returned job IDs before polling, including across restarts.
The guided adapter waits before native consume, while the background monitor can finish the same authorized retry after interruption.
Uncertain submissions are never retried automatically, and repeated refusals remain untranslated.
Original payloads and responses remain available beside the clarification evidence.
The request inspector groups a clarification or a validation retry with its original request and offers Original, Clarification retry and Retry tabs inside that selection.
Response, source/context, exact payload and usage follow the selected attempt without another backend read; the latest attempt opens by default.
Both replies come from retained receipts, separately from the refusal-filtered native consume result.
Live workers record the parent before sending.
Older Live pairs require an exact, unambiguous match of payload, file and source identities; unrelated or ambiguous requests stay separate.
Validation retries record their first attempt the same way; in older runs only an attempt that a later validated response replaced leads the following attempts at its lines.
Grouping is presentation-only: raw receipt indices, submission guards and billed usage stay intact.
File line counts and rejected-request counts follow each request's latest attempt, so retried lines count once.
Each clarification retains the original source and instructions with one appended clarification.
New MV/MZ state runs also freeze compatible state-call grouping before submission.
The app adapter delegates extraction and field writing to the native state handler, groups only calls with identical instructions and matched system/glossary/SFX context within the saved request limit, and reuses the saved response partition during consume.
Grouped requests carry their state-ID and field associations as context beside the unchanged LineN source/output schema.
Actor-substitution calls and note calls retain their original boundaries.
New MV/MZ runs freeze a single-pass choice policy, the [event parser's](../backend/dazedtl/engine/modules/rpgmakermvmz.py) `CHOICE_COLLECTION`: built-in menu choices are visited only on the first event pass, retaining their scene context.
The write pass cannot queue a duplicate during preparation or consume/retry a rejected choice again.
Pass state is local to the worker thread; identical text in different menus remains independently contextualized.
Older frozen plans retain their original preparation and recovery behavior.
New MV/MZ runs also freeze a speaker-context policy, which enables the [event parser's](../backend/dazedtl/engine/modules/rpgmakermvmz.py) `SPEAKER_CONTEXT` fixes.
Existing translated code-101 nameplates still supply dialogue context; unnamed messages clear the preceding speaker.
Implicit square-bracket nameplates must pass short-name plausibility checks, so bracketed tutorial prose receives normal text instructions instead of the nameplate prompt.
Adjacent text with its own retained original remains a separate translation unit, preserving previously translated neighbors and source metadata.
Estimates, Live and Batch use the same policy; older frozen runs retain their original parser and request identities.

### Batch execution and recovery

The provider adapter normalizes cancellation acknowledgements before the guided handler saves them; the saved status takes precedence over a stale worker poll.
Retrying cancellation checks provider status first, so an already cancelling or terminal Batch does not receive another cancellation request.
Pending provider counts and errors may be null; saved polling receipts take precedence over earlier file-scan progress without rewriting run evidence.
The [Batch monitor](../backend/dazedtl/translation/batch_monitor.py) retains the last outcome while rechecking recovery records; the check itself does not make a run active.
Late observations recheck ownership and worker state before publication.
Saved terminal receipts and their counts take precedence over monitor polls, and a resumed or completed worker supersedes its old monitoring view.
For runs split across provider Batches, inactive summaries retain original request totals and finished outcomes across completed chunks, without counting clarifications again.
Current provider work keeps its own counts.
Status text pairs with an active spinner or an outcome icon; saved success requires verified output without outstanding work or reported issues.
Missing counts stay unknown, and provider completion remains separate from saving local output.
The app-owned [OpenAI Batch window](../backend/dazedtl/compatibility/batch_window.py) fills the configured total input-token allowance with multiple provider jobs and refills when any terminal job releases capacity.
It targets one quarter of that allowance per job, capped by the native chunk target, so a slow request cannot hold the entire window.
Individual requests remain intact, and provider file/request limits still apply.
A shared connection/model lock accounts for other Guided runs, clarification attempts and uncertain submissions before reserving capacity.
Partial request progress does not release a pending job’s tokens.
Only the owning worker advances its approved queue; the background monitor restarts that worker after interruption and collects its retained responses.
A fully successful provider receipt with a matching submission manifest remains submitted while awaiting download; missing fetched responses or conflicting evidence retain submission uncertainty and outstanding work is never automatically resubmitted.
The [submission journal](../backend/dazedtl/compatibility/batch_continuation.py) records a create the provider refused outright with a client error, such as OpenRouter's HTTP 402, so its requests read as never sent and a new approval may send them; timeouts, conflicts, server errors and lost responses can follow a successful create and stay uncertain.
A failed Live request reads as never sent only when every HTTP try inside it failed to connect or was refused outright, as the [transport observer](../backend/dazedtl/compatibility/transmission.py) records, because SDK retries can hide a processed try behind a later refused connection; anything else stays uncertain.
Cancellation binds one provider Batch and its request mapping through a project-owned, one-use review; it retains the queue and receipts.
Terminal collection uses the recorded connection and retains successful responses.
It settles any authorized clarification Batch before native fetched-results consumption, including partial results from canceled Batches.
Unknown or conflicting responses retain their recovery guard.
Consumed Batch history plus a matching frozen plan and unchanged, complete output receipts settle finished requests without inventing per-request validation.
Missing outputs and native mismatches retain unresolved receipt states; identical text in different known files does not create an overlap.
The backend-owned [Batch monitor](../backend/dazedtl/translation/batch_monitor.py) checks interrupted runs automatically across registered projects, independently of the current screen and native worker pointer.
A Batch approval binds the full frozen queue and plan.
After an app interruption, the original worker continues that unchanged approved queue, skipping recorded provider requests and preserving already collected results.
Explicit stops, provider cancellations, newer approved overlapping runs, changed scope and uncertain submission outcomes prevent automatic continuation.
Older app approvals require the matching saved quote and prepared request ledger before adopting the same binding.
Native submission is wrapped by a durable intent/returned-ID journal; known receipts are recovered after a checkpoint interruption, while unknown HTTP outcomes are never submitted again automatically.
Provider reads and downloads run outside the API lock; cached observations feed the existing application observer.
Collection rechecks ownership, worker state and shutdown before committing.
Automatic local consumption requires both a durable fetched marker and submission receipts covering every prepared request.
The controller and worker-launch boundary recheck that coverage: collecting one completed chunk cannot turn an unsent remainder into a full consume pass.
Incomplete submissions retain their downloaded responses while the approved remainder continues.
Unapproved or changed work requires its own estimate and paid review; an app restart does not require a second approval for the unchanged original queue.
Clarification receipts can extend as later original chunks arrive, preserving both original responses and settled retries without repeating them.
Local consume failures with received responses expose Retry saving results instead of an automatic restart loop; Batches with confirmed zero successes are left failed without attempting an empty consume pass.
No pause/resume monitoring control is presented.

### Evidence and validation

Guided process views read saved queue fragments, manifests, results, and file receipts separately.
The Batch evidence adapter archives approved request mappings and responses before native scratch cleanup.
Older consumed Batches can display translations only when their retained source identities and native validation records match exactly; these are identified as validated translations, not original provider bodies.
Missing evidence never establishes successful validation or billed usage.
Live workers retain each response body and its refusal/finish metadata before validation, separately from the native accepted values and recorded usage.
Native cache acceptance settles only its matching request; rejected attempts remain inspectable without being offered as translated text.
A refusal cannot enter game dialogue, including in older runs without a clarification policy.
Historical refusal prose is flagged and excluded from validated-result reuse without rewriting saved output or inventing missing response bodies.
Batch workers retain [native validation receipts](../backend/dazedtl/compatibility/batch_validation.py) in the existing process ledger, bound to the consumed request key, source, file and response hash.
Native cache acceptance records a pass; a normally returned validation call marks its remaining responses failed, while exceptions leave them unresolved.
These receipts do not depend on refusal wording, text logs or whole-file completion.
Historical runs retain the exact log-matching fallback.
Live and Batch inspectors show generic validation passed/failed outcomes for the selected attempt and keep failed bodies readable; receipt-only responses remain neutral until validation is known.
The [Live validation reader](../backend/dazedtl/compatibility/live_validation.py) settles older rejected retry groups only when the completed run's frozen plan and output hashes match, every attempt has a received receipt, and one structured native mismatch record matches the exact source and unambiguous request context.
The final formatted reply can be shown as recovered log evidence; earlier bodies remain unavailable.
Missing, changed, ambiguous or uncertain evidence keeps the historical request unresolved.
A failed attempt followed by native acceptance remains inspectable without marking the successful file incomplete.
The [checkpoint adapter](../backend/dazedtl/compatibility/checkpoints.py) records verified native JSON progress saves.
Live resumes read those partial outputs through the native file reader while preserving frozen input snapshots, and reload validated responses from the same run to cover the gap before a checkpoint.
Batch consume keeps its original input grouping and saved provider responses.
Known pre-consumption Batch checkpoints remain scratch data even after approval.
The collector exposes verified partial outputs without overwriting newer staged copies.
The request reader is project-bound and read-only.
Its Response tab shows retained replies or full error details, including nested provider diagnostics.
Live failures retain bounded, credential-redacted SDK response bodies (including wrapped exceptions and plain-text bodies), separately from accepted translations; unavailable historical bodies are never invented.
Provider status and collection belong to the existing worker and Batch monitor.
The selected request updates automatically from shared observer receipt changes, with a spinner while that request is at the provider; a failed detail read offers a local retry.
The Batch inspector keeps a selectable batch sidebar beside its request reader, with separate unsent or unlinked requests.
Clarifications join their original batch through the recorded parent ID; they do not increase the original request count or duplicate its source rows.
Request selection stays within the selected group's recorded request indices, and each affected request retains Original and Clarification attempt tabs.
A pending or failed clarification remains visible in the group's status.
Counts and file overlap never infer membership or parentage; an unlinked clarification remains separate.
Content tabs and request selection remain local view state, and a missing response shows only its waiting or unavailable state.
A fully successful Batch with matching submission receipts may identify requests as finished at the provider while download is pending; partial provider totals never identify individual results or release execution guards.
Validation mismatches are file warnings with a direct action into the request inspector's rejected-translation filter.
Provider completion and local validation stay distinct.
The [Batch validation reader](../backend/dazedtl/compatibility/batch_validation.py) matches retained native acceptance/rejection records to exact source identities and provider responses only after verifying the consumed submission mapping, frozen plan and unchanged output.
Matching rejected requests retain their source text and can enter a fresh estimate; matching valid requests remain settled even when another request in the same file fails.
Missing, ambiguous or conflicting evidence keeps the affected requests unresolved, and older file-only mismatch records show an unknown count with log inspection.
Parsed validation records are cached by file stamps and exact input/response bindings; observations do not rewrite history or rerun validators.
Rejected responses remain inspectable as raw evidence and never appear as saved translations.
The [choice history reader](../backend/dazedtl/compatibility/choice_history.py) identifies an older unused response only when one extra context-free request accompanies the exact contextualized requests for every physical menu, and each menu's saved text and original metadata match a validated sibling response.
Frozen input/output hashes and submission mappings must still match.
Proven extras are labeled Unused duplicate, keep their provider bodies and usage, and link to the requests whose wording was saved.
They do not count as validated or unresolved work; ambiguous associations remain unresolved.
Menu locations are cached by source/output file stamps, without rewriting historical runs.

### Result reuse

New workers record durable submission intent separately from preparation, source identities independent of model/prompt/chunk size, and native-validated response values.
Continuation reuses these values locally across expanded or narrowed selections when the relevant source bindings and file versions match.
If compatible runs contain different validated wording for one identity, the newest run by creation time supplies the reusable value; historical alternatives stay unchanged and do not block preparation.
Existing working translations still go through the native skip-translated behavior.
Every selected file is still parsed; untranslated or changed text within a previously translated file remains eligible.
Reuse is per text identity, never a file-complete skip.
New provenance associates validated identities with their files so changing one source does not reuse its old values.
Verified completed files from partial runs are collected only when their frozen inputs still match the working copy; newer edits are retained.
When a call mixes reused translations with remaining source spans, a mismatch in one span preserves that span's native fallback and continues the others.
The adapter retains successful translations, all attempted usage and the final mismatch flag without changing native chunking, context, validation or retry rules.
The MV/MZ comment handler also retains aligned partial results instead of discarding every comment after one rejected chunk.
Its length/type guard and the separate name-preflight checks remain intact; native mismatch records still identify the file for review.
Source identity currently treats repeated identical strings within one file and phase as aliases.
Legacy queues without file provenance use a conservative source-text intersection within shared saved files/phase.
Interrupted old Live runs without request evidence flag only their shared file/phase scope for the advisory; their send outcomes cannot be reconstructed locally.

### Run history and inspection

Run history is the single run list.
Its shared inspector owns provider cancellation, stopping or continuing an approved OpenRouter queue, collection/saving recovery and reviewed reapplication of verified output.
Cancellation controls bind the selected provider Batch, including its linked clarifications; concurrent jobs keep independent targets.
Run-wide queue and recovery actions remain distinct from request selection.
They use the shared guarded action feedback, preserve the existing one-use reviews, and render the single application observer’s receipts without another polling loop.
Approved project-owned runs remain in History automatically, including failed and canceled runs.
Legacy history remains readable; new unapproved preparation is excluded.
The native pointer is not the ownership registry.
Creation order determines the newest attempt in each task; an active worker stays visible, while a newer estimate or different scope never falls back to an older overlapping failure.
The application-wide run view represents active work only.
Runs have no hidden-history preference or separate output-copy action; Apply and the translated-folder tool remain the guided output workflow.
Legacy `kept_failed_runs` keys remain an ownership-discovery source only; they do not hide runs or settle receipts.
Unresolved submissions remain inspectable in history and subject to the existing execution guards and overlapping-charge review.
Saved run status never vetoes an explicitly requested new Guided translation.
Live and Batch preparation and cost approval allow overlapping submitted, uncertain or received requests.
The existing cost review shows an advisory about possible duplicate charges when the estimate overlaps unresolved history or that history cannot be read; no extra confirmation or recovery step is required.
This advisory is saved with the estimate for the Batch review without reconstructing history during observation.
Fresh source/scope/settings checks, project ownership and one-use approval tokens still apply.
Older runs and their receipts stay intact, and automatic recovery never gains authority to resend uncertain work.
File inspect buttons open the same [run inspector](../app/src/features/guided/RunInspector.tsx) used by Run history, independently of checkbox selection.
The owning attempt and exact file-linked request are selected locally; a current estimate takes precedence over older completed output.
Files without a linked request show that limitation without borrowing another file’s payload.
Files without an attempt still open the shared inspector’s file reader.
Source retains prepared text and matched context, while Response pairs only matching LineN keys or equal-length validated Live responses and retains raw replies when pairing is ambiguous.
Request text shows each placeholder that replaced a control code as sent, marked so its position can be checked; the request does not record which code it replaced.
A run opens on the request a reader last viewed, or on the first that needs attention: a submission its ended run never confirmed, then a failed or rejected one.
Missing context never substitutes current guidance.
The cost-review preview keeps Text, Context and API payload tabs, with request paging outside the reader.
File contents is available for the selected file through the project-bound [file reader](../backend/dazedtl/translation/file_preview.py), which reads staged output, then working input, then current game JSON without preparing or modifying files.
It identifies this current text separately from saved run evidence.
It omits text identical to retained source, keeps changed and unmatched fields, and never claims request eligibility.
The reader loads only after opening its tab and retains its search, page and scroll while switching content tabs.
Translate embeds the existing [FileSelection](../app/src/features/guided/FileSelection.tsx) component rather than a second picker.
Its shared virtual list and selection logic retain Ctrl/Cmd toggles, Shift ranges and keyboard movement.
A separate Inspect icon does not change scope; the open file is marked independently of selection.
File status follows that file's request receipts and verified output independently of checkbox selection or the current attempt.
The file list uses the shared display states.
Untouched files show Not started, including files whose requests all failed without returning lines, with that reason in the detail; verified passes with no new requests show Ready to apply.
Preparation, queueing, provider work, cancellation, collection and saving show Working; a pending cost approval shows Needs review without a spinner.
Needs review also covers partial, rejected or unsaved results and never establishes completion.
Ready to apply requires verified full output or explicit evidence that no requests were needed.
Applied means the game matches the saved output, or the latest Apply receipt holds it or an output a later run built from it, through [applied_versions](../backend/dazedtl/translation/guided.py).
Hand fixes, Line widths and QA fixes in the game therefore leave it Applied, as does a later phase's Apply; another Apply or a restore replaces the receipt, and Reload from game retires the file's runs.
Recorded output that is missing or changed shows Blocked, and a file changed in the game since its working copy was made shows Outdated.
Detailed states and request counts belong in Inspect and the approval dialog.
The latest run's failure, or a Batch that could not be confirmed as sent, shows on its task with the reason instead of a finished notice; collection errors and rejection details remain in the inspector and run views.
Dismissing that [banner](../app/src/features/guided/RunFailure.tsx) is a browser-profile preference for the run and a fingerprint of its reason; it hides no run, receipt or execution guard, and a different reason shows again.
The observed `workerStatus` retains the actual worker state separately from public monitoring activity.
File ownership, saved metrics and task completion use that worker state, so a background check cannot promote an older run or make its whole scope look queued.
Automatic Batch monitoring cannot mark every file as submitted or override saved progress: In progress for provider work requires the file's latest submitted requests to be mapped to an explicitly active provider Batch, using the shared provider-state rules.
Terminal, unknown, missing or unrelated Batch receipts cannot make retained submissions appear active.
Pending collection also requires matching completed-Batch and finished-request evidence.
These display rules never settle submissions or release execution guards.
A finished Batch collection can identify files with no new requests only when its recorded builder provenance covers the selected scope; deduplicated callers remain included, and absent legacy evidence stays unknown.
Provider-waiting rows and active Batch stages use the shared activity indicator, while cost approval and files with no requests stay still.
Selection locks during active work while search and inspection remain available.
Per-file cost and processing time come from native result receipts, retained beyond the log cap; Batch collection figures are excluded and consumption time excludes provider waiting.
The file list retains cost and time from the latest run that changed the file, comparing its recorded output hash with its frozen input hash; estimates, pending work and unchanged passes do not replace those metrics.
Missing receipts for a changed file stay unknown.
Line amounts follow the same receipts through [fileLines](../app/src/features/guided/translationView.ts): the lines a file's latest run saved, out of the lines that run prepared, counting each source request once at its latest attempt; a later "nothing to translate" check closes the file at what is done.
A Live run prepares requests as it works, so its files show only the lines saved so far until it ends, and Apply leaves them out until then.
Estimates carry no per-file lines, so a file without a run shows no amount; the Project page totals the known amounts with files applied and the recorded cost.
Incoming observations preserve the reader's selected file, request, tab and scroll position.
Selected request receipts update automatically; older records without file provenance identify their scope limitation.
History, on the Project page, has separate translation, estimate and other-activity tabs.
A row shows its message only when it adds to the row's title, and other activity shows a status only when it is not Complete.
Display outcomes use existing observed receipts: estimates, no-request attempts, verified output, partial progress and unavailable output stay distinct.
Unresolved submissions remain marked for review in history.
Search and filters operate locally on the already-observed summaries; In progress includes submitted provider work even after its local worker stops.
Its request inspector uses Source, Response and Technical, plus File contents when a file is identified.
Source retains matched context; Response shows the retained reply or a concise missing-response state.
Technical starts with the run record and exposes collection errors, provider receipts and the exact request, including when no request payload is available.
Request failures stay with the selected attempt’s response and technical payload; request-bound provider errors do not become run-wide diagnostics.
File-only legacy validation evidence stays explicitly scoped to its file without identifying a guessed failed request.
The picker is the sole request navigation control and has no hidden failure or file filters.
Raw worker logs are not a separate content view: Technical ends with the retained log tail, which the compatibility readers still use as evidence.
Other-activity records open with their status, saved result and log in the same presentation.
Request selection and tabs persist locally without storing payloads in browser preferences.
The inspector has no separate provider-check control or transient remote status overlay; tab changes never contact the provider.
Saved translated output and applied files are separate counts.
Active per-file request states take precedence over retained checkpoints; a resumed worker takes ownership of its rows even when a newer completed attempt exists.
Live rows also retain the worker's current filename from `itemProgress` between requests, including after rejected replies.
The completed-file counter identifies the last finished file and cannot establish current activity; native command totals are not translation percentages.

### Apply and release

Completed Batches offer Reapply in the shared run inspector.
The review resolves the chosen project-owned run independently of the current selection and freezes its hash-verified retained output; it never substitutes the latest working translation or submits provider work.
Missing or changed historical files cannot be reapplied.
Publication uses the same reviewed overwrite and restore receipts as ordinary Apply.
An older Apply receipt does not establish that the current game still matches a run’s output.
Explicit text Apply is a full overwrite: it binds the frozen candidate and destination scope while accepting intervening game-data edits.
Its review names the files edited in the game since their last Apply, whose edits it replaces.
Its one-use confirmation retains the reviewed file list for execution guards.
A failed confirmation keeps its error visible and offers Refresh preview; it cannot resend the consumed token or automatically execute the replacement review.
Apply captures the actual overwritten bytes for rollback at execution.
Fitting, QA and restore keep their existing exact-before checks; no background synchronization is performed.
Reviewed Apply accepts saved partial output regardless of earlier Batch status, unresolved requests, provider work or collection.
It validates and freezes the saved JSON without requiring translation completion; untranslated content stays as saved.
Isolated translation workers do not veto Apply, while runtime operations, source/output checks and one-use publication guards still apply.
Applying output does not settle request receipts, cancel work or establish translation completion.
Compact run counts preserve preparation, submission, receipt, validation and application as separate evidence, and full request/provider errors remain available in Response & error.
Audited assignments produce variable mappings, and the later comparison step consumes only mappings matching its selected events.
Their controller exposes specific engine actions through one-use, project-bound previews; source, selection, settings and working-output changes invalidate the relevant preview.
Explicit full-overwrite Apply does not track runtime JSON conflicts.
Guided release freezes the current runtime scope and original-source bindings through an app-only, one-use preview.
Patch packaging saves its checkpoint and workspace restore point as part of the same operation.
The app-owned clean packager uses one inventory for inspection and writing, retains player documentation, excludes known private and translator material, and verifies the source and destination before atomically replacing a ZIP.
Guided patches add current applied-image receipts and explicitly reviewed image/font paths to the runtime scope.
Local patches omit GameUpdate configuration; clean ZIPs include it only with the frozen engine's verified public commit stamp.
Player updater scripts remain included but cannot update an unstamped local build without configuration.
Archive availability describes the saved ZIP on disk, never freshness against later game edits.
Archive names and additional asset choices are retained per project, with separate game and patch names.
Neither operation manufactures a user-review record or completes Len's report-based QA.
The project helper cannot invoke Guided packaging; its separate QA requirements remain in force.
Legacy Guided review receipts remain readable for existing records.

## Plugins and images

Guided Plugin files and Images are Translate tasks; positions saved by earlier stage layouts open them without rewriting saved run records.
The [plugin service](../backend/dazedtl/plugins/service.py) owns retained investigation, working copies and reviewed publication for MV/MZ root and `www` layouts.
The assistant decides which plugin text players see; the user does not review files or individual strings, and reviews only what Apply writes into the game.
An Acorn AST inventory and recursive decoded parameter paths bind reports to exact source bytes without evaluating plugin code.
Original Japanese database fields, notetags, command arguments and parameter evidence come from a verified source backup even after runtime JSON has been translated, so a task cannot start without it.
Known lookup values, code keys, embedded expressions, serialization structure and control tokens remain protected by the app and are never asked about; a file with nothing else, and no JSON it loads, needs no investigation.
A translated line may keep only a leading Japanese tag that unchanged code in its file matches with `startsWith` or `indexOf`, such as a script parser's `ア:` speaker tag; any other Japanese left in a target fails the check.
Dynamic configuration, malformed data, unreadable sources and unsupported Ace publication remain explicit blockers.
A parameter value that looks like JSON but does not decode, such as a script, stays one leaf the app protects and does not block the rest of its file; saved scans are redone once when these scanning rules change.
The user can keep an unreadable file unchanged so the required task can finish; the choice lapses when the file fails for a different reason, and a listed plugin whose file is gone has nothing to translate.
Only independently investigated static plugin-loaded JSON dependencies enter this scope; ordinary event and database files retain their existing text phase.
The clipboard task edits owned working copies, while runtime Apply stays behind an app-only, one-use exact-file preview.
Request hashes and publication journals retain authority in the app profile, with candidate freezing, verified backups, failure rollback, restart reconciliation and another review for restore.
One copied plugin task covers every plugin file, from investigation through translation and validation, using the [project helper](translation-contract.md#project-helper).
Each request asks only about what is left: undecided text in files not yet settled, then the chosen text of files without a checked translation, with the reason a file's last translation failed.
A report settles exactly what it answers, so the assistant can report part of a request and continue with the remainder; an undecided occurrence cannot inherit an earlier finding's safety.
Confirmed active display text is chosen automatically; inactive and default-only text stays excluded.
Translation requests carry the game's established English: guidance files, the Translate stage's output, the game's applied data and the reference games.
Each result stays bound to the request that asked for it, and publication checks the file against that request.
The helper cannot preview or publish runtime files, and only app-issued automatic tasks can continue.
Repeated continuation of the immediately preceding request returns its existing successor; stale tasks cannot replace newer work.
Copying the task again while work is left returns the open request when its scope still matches the scanned sources, guidance and originals, so a saved partial report is extended rather than orphaned.
Once nothing is left, a copy asks the assistant to recheck every decision with its earlier findings, for text the user found untranslated in the game.
Apply and restore reviews omit hashes, working-copy and backup paths; execution rechecks the exact reviewed files.

The [image service](../backend/dazedtl/images/service.py) owns a project-scoped SQLite inventory, retained selection, discovery and editing contracts, saved reports, and runtime application receipts shared by Guided and Image Manager.
Indexing runs incrementally with cancellation; the renderer reads metadata in bounded windows and thumbnails through a [queue](../app/src/features/images/thumbnails.ts) with a cache bounded by size.
Windows and thumbnails on screen load first, and the rest of the view follows, nearest first, so scrolling finds its images ready.
Thumbnails are WebP at the screen's pixel density.
Previews decode each image once and hold the service lock only for the inventory lookup; the [server](../backend/dazedtl/api/server.py) answers them on a few workers outside the engine context, which redirects stdout process-wide, while every other request still runs in turn.
The observation revision leaves out the user's choices, so saving the selection or scroll position reloads no window; the selected images the filters hide are counted on their own, and a reload keeps each window on screen until it is replaced.
The selection is the list to translate, and the manager walks it through four steps derived in [imageFlow](../app/src/features/images/imageFlow.ts): the assistant investigates, the user chooses, the assistant translates, the user applies.
A click only previews, so looking never changes the list; the tick box, Ctrl/Cmd and Space toggle an image and Shift only adds, with [selectItem](../app/src/ui/selection.ts), and a Shift range that reaches past the loaded windows reads the images between in bounded runs.
The [viewer](../app/src/features/images/ImageViewer.tsx) fills a full-height column beside the task, toolbar and grid, because the preview is limited by height more than width; it reads the last clicked image at full size, unscaled when it fits the backend's largest preview, while its tile's thumbnail stands in; the saved view remembers which image it shows, as it does Compare's.
Discovery reports bind project, inventory revision, exact scope and source hashes, with per-image examination evidence.
Unexamined, failed, unreadable and changed sources remain unresolved; detector misses alone cannot certify no text.
Manual choices survive recommendations and filtering, and only byte-identical sources can reuse discovery evidence.
An investigation report ticks each image it newly recommends once and opens the grid on the list, so an image the user took out stays out when the same request saves again; a report whose every image has a result completes the request even without its flag.
The translation task covers the list's images not yet in the game and makes their editable copies first, leaving out images that cannot be edited.
Apply to game applies the list's translated images; a list that a click replaced in earlier versions gets its copied translation task's images back once.
Editing reports bind original and candidate hashes and a review version; changing either invalidates review.
Compare shows the discovery finding and current AI-review evidence; hashes and backup paths stay out of reviews because Apply rechecks the exact reviewed bytes.
Apply freezes the included batch and blocked reasons in a one-use preview, preflights every included asset before publication, and attempts runtime and metadata rollback on publication failure.
Publication freezes candidate bytes and journals the reviewed source, output and original-backup hashes before writing runtime files.
Restart reconciles only those exact authorized bytes, records partial or conflicting publication honestly, and retains reviewed restore for recovered outputs.
Preserved originals and durable receipts support reviewed restore without removing editable copies or editor work.
The authenticated project helper exposes read-only image state, listing and previews; image application remains an app review.
Clipboard handoffs never claim an external assistant is running.

Plugin and image progress in the game folder belongs to the project that saved it, and projects are keyed by source path, so a moved or copied game, a new profile or a reinstall opens that work under a new project.
[Foreign work](../backend/dazedtl/foreign_work.py) reports it in the snapshot instead of failing, and the shared [ForeignWork](../app/src/ui/ForeignWork.tsx) panel offers the choice in Plugin files and both Image Manager hosts.
Nothing is used or moved until the user chooses, and each choice binds the hash of the saved state it was shown.
Using it rebinds the state after rechecking what the new project can verify.
Findings, choices, working copies, reviews and application records carry over; copied requests do not, because their authority (plugin request hashes in the old profile, image requests bound to the old project) cannot be checked here.
Their reports are never accepted, plugin results not yet applied need a new check, and image tasks resume from them through a new request.
A plugin application journal is authorized again only while a file still carries that application and its journal and backups match the receipt exactly.
Image restores need only the originals saved in the game folder, so they carry over unchanged.
An interrupted publication blocks the takeover, because only the profile that authorized it can reconcile it.
Starting over moves the work folder to `.dazedtl/archived` under a dated name with every file kept; editable image copies and preserved originals outside it stay in place.

The optional [image text editor](../backend/dazedtl/images/editor.py) retains the toolkit's boxes, target-only exchange import, rendering and undo process behind compatibility adapters.
Its local OCR capability is limited to installed offline resources, with no hosted fallback or model download.
Native Image Text translation uses the preserved isolated manual runner with project-owned frozen inputs, a current estimate and one-use paid approval, independently of JSON translation runs and image application.
These runs have no run inspector, so a failed run's log tail appears beside its status.
Import revalidates the exported source scope and copies targets only; rendering still requires structural validation and image review before runtime application.

## UI and state decisions

### UX principles

Strive for [Nielsen's ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) when designing and reviewing this tool.
Make current state and the next useful action visible; use translation tasks and familiar language; offer clear exits and recovery; keep shared controls consistent; prevent scope and spending mistakes; make prerequisites visible instead of requiring memory; support both guided and experienced use; prioritize relevant actions; give errors a practical recovery path; and put concise help beside the task that needs it.
Use these principles to evaluate real workflows, rather than adding extra panels or confirmation steps to satisfy a checklist.
Give each idea one name and keep it everywhere: Apply only means writing into the game (settings are saved or used); Backups are copies you can restore and Versions are the Git history used to merge game updates; Line widths are the per-line character limits that the line width check enforces.
Assistant-led is the UI name of the method built on Len's game-translation skills, and code and records keep the `len` identifier.
Its starting prompt runs the whole method without the user: it asks only for spending approval, a missing API connection, denied access or a decision no source evidence settles, and a check it cannot make, such as a screenshot, stays pending instead of stopping the run.
The assistant's own plan pays for every turn, so new games start on API Batch (Live when the connection cannot batch) and references are read as their phase begins.
In both methods the [investigation skill](../backend/dazedtl/engine/data/skills/localization_investigation.md) runs one discovery pass, and its three blind passes only when the game asks for Thorough investigation; the setup loaders keep the chosen section, so a copied prompt never holds both.

### Visual design

The app ships [Inter](../app/src/assets/fonts/Inter-OFL.txt), so text widths and wrapping match on every platform; system fonts only supply scripts it lacks.
Japanese system faces lead those fallbacks, so game text keeps Japanese kanji forms and its weights instead of whichever face the platform picks.
The rounded [Fredoka](../app/src/assets/fonts/Fredoka-OFL.txt) sets only the wordmark and page titles, through `--font-family-display`, and falls back to Inter for characters it lacks.
Text uses the five sizes and three weights in [tokens.css](../app/src/styles/tokens.css): page titles, then task, dialog and section titles, then body text and row titles, then secondary text and controls, then captions.
Headings and emphasis are semibold, row titles medium, and everything else regular; stylesheets name a size token instead of a pixel value.
Each region has one heading: a page title, then section or panel headings, never a stack of headings before content; headings inside a dialog body sit a step below the dialog title.
Paragraphs and notes in page and dialog bodies stop at `--measure`, about 72 characters; tables, editors, grids and row labels keep the width their layout gives them.
Form fields stack their label above the control; Settings and dialog forms, where many short fields line up, use a label column.
Related checkboxes share one label in [CheckGroup](../app/src/ui/FieldRow.tsx) and line up in columns instead of stacking as separate fields; a count that completes a choice's sentence, such as a row limit, sits inline in it.
Choices and short values are at most 24rem wide; paths, search and free text use the wide variant.
Buttons, single-line inputs and selects share `--control-height` and `--control-radius`, so a field and its button line up; textareas keep their own height, and the shell's sidebar and project switcher size themselves as chrome.
Spacing comes in the 4px `--space-*` steps: 8 inside a group, 16 between rows and 24 to 32 between sections; `--space-half` only nudges small marks into place, and 1px only aligns borders.
Corners use `--control-radius` for controls and small marks, `--panel-radius` for panels and `--dialog-radius` for dialogs; popovers and menus share `--shadow-popover`, and dialogs use `--shadow-dialog` over `--color-backdrop`.
Pick a control by the choice it offers: a checkbox for on or off, [SegmentedControl](../app/src/ui/SegmentedControl.tsx) for one of a few short options, [OptionCards](../app/src/ui/OptionCards.tsx) for one of a few that each need a line of explanation, a select for longer lists, and [ComboBox](../app/src/ui/ComboBox.tsx) when a typed value is also allowed.
The palette pairs teal-tinted neutrals with a cyan-green accent, so the app reads as its own tool rather than a stock dark theme; done marks use a leaf green so finished never looks selected.
Color has three accent roles: accent for interactive text, focus and the edge or underline that marks what is current, accent strong under white text for the one primary button, and accent subtle for selected surfaces (the current sidebar entry, a selected row).
The current sidebar entry adds an accent bar on its start edge; the selected tab and the current stage keep the text color over an accent underline, and the current stage's number fills with the accent.
A panel whose first row names it and its state, such as the assistant task and the active connection, gives that row the shared `panel-header` tint.
The dazed cat is the app's mark, drawn from the original icon: its teal tile as the window icon, and its accent outline in the top bar and leading the Project page's welcome row when no game is open.
Inside the app the cat is always the outline, so the top bar does not repeat the tile that title bars show beside it; it appears nowhere else, so it stays distinctive.
Green, amber and red mark status only; surfaces, lines and text each have a few named steps, and a new screen picks from them instead of adding a color.
Image canvases keep their own `--color-canvas-*` checks and `--color-mark-*` box marks, because they are drawn over game images rather than the app's surfaces.
Every literal size, weight, color, spacing step and radius lives in [tokens.css](../app/src/styles/tokens.css); [styles.mjs](../scripts/styles.mjs), part of the build checks, rejects literals in any other stylesheet, so a new value starts as a named token.
The top bar, footers and sidebar take their sizes from tokens.css; below 1100px wide the sidebar becomes a rail of icons over short labels, so small windows give the task the width.
Icons appear in navigation, on actions that leave the app (opening a folder), on menus and disclosures, and on Add; other actions are text only, and ActionControl's `icon` carries the marked ones.
Footers start with Back and end with Continue; the task's own action sits just left of Continue and is the primary until the task is done, and then Continue is, so each screen has one primary.
Guided task views hand the footer their `secondary`, `action` and `next` controls, and [GuidedWorkflow](../app/src/features/guided/GuidedWorkflow.tsx) places them in that order.
A task's main action lives in its footer; rows hold supporting actions, and headers hold task-wide views or settings.
A task's purpose is its one-line TaskHeader description.
Consequences sit in the review dialog of the action they qualify, a precondition sits beside its action in the footer, background goes in a help popover beside what it explains, and status stays visible.

### Workflow and shared presentation

Use the flat, compact [Settings](../app/src/features/settings/Settings.tsx) and [Project page](../app/src/features/project/ProjectPage.tsx) implementations as page examples.
The sidebar has three places: the Project page holds everything about the game, Translation holds the work, and Settings holds the app.
Each game has one translation method, chosen in [MethodDialog](../app/src/features/project/MethodDialog.tsx) when it is first opened and kept in the project registry; games opened before the choice keep the method they already have work in, and changing it keeps the other method's work.
The one Translation entry opens that method's workspace.
The Project page's Status, History, Game updates and Backups tabs serve both methods.
Status shows where a Guided project stands from the observed snapshot through [guidedProgress](../app/src/features/guided/progress.ts): the next unfinished required task, every stage's tasks with their completion and the last activity.
Its one Continue opens the next required task, and the saved workspace position appears beside it as a smaller Last opened link unless it is a finished task before the next one; with every required task done, Continue resumes that position.
A one-task stage shows no done count, and an optional task not yet done says Optional instead of showing an empty mark.
Plugin files and Images say Needs review instead, on the Project page and their tabs, while work another project saved waits for the user's choice.
Plugin files completes from the same snapshot once every plugin's player text is translated with nothing waiting to apply and every unreadable file is kept unchanged, Images once the translated images in its list are applied, or an investigation leaves nothing ticked, and Build release ZIP while a saved ZIP still matches the game; optional tasks never block the next required task.
Translate's Run history opens that stage's runs and estimates in a sheet over the task, with Inspect stacked on top, so closing returns to the task; Project › History lists every run.
Setup's backup link opens the Project page's Backups tab, and the Translation entry returns to the same task.
Reviews that belong to the Guided workspace (re-applying or resuming a run, the update checkpoint) open there when the Project page asks for them.
Screens use four kinds of surface, each with one job.
A page is somewhere you work or browse, reached from the sidebar and kept when you leave and return.
A tab is another view of the same thing, and switching never loses your place or drafts.
A dialog holds one decision or one focused edit and ends in an explicit choice; it never opens another dialog except a detail view that returns to it, and a dialog that leads to a review closes before the review opens.
A menu is a short list of choices that closes when you pick one.
New pages start from one of three templates: the task page (stepper, task tabs, TaskHeader, the task's panels, its work area, footer), the project page (header, tabs, a body and footer per tab) and the decision dialog (the decision as its title, what will happen, explicit footer choices).
Compose shared UI primitives with design tokens; editing footers sit outside scrolling content.
A dialog whose tabs hold panels of different heights stacks them with [StackedTabPanels](../app/src/ui/Tabs.tsx), so switching tabs keeps its size.
Settings, the Project page and [Assistant-led](../app/src/features/translation/Translation.tsx) share the editor page model: a header, tabs, a scrolling body and a footer per tab; Assistant-led's Progress tab leads with the assistant's status and its Options tab holds the choices made before starting, its footers end with its starting-prompt copy, its context documents use the same DocumentEditor tabs as Guided guidance, and its Images tab hosts the same Image Manager as Guided.
Every stylesheet loads through [index.css](../app/src/styles/index.css) in a cascade layer: tokens, base, shared UI, the app shell layout, then features.
A feature's rules override shared primitives regardless of selector specificity, so add a new stylesheet there and keep selectors simple instead of raising specificity to win.
Layouts must remain readable and usable across displays ranging from small laptop monitors to large 4K monitors or TVs.
Size and reflow content using the available window space and system display scaling; keep actions accessible on smaller displays and use larger displays without excessive stretching or gaps.
The desktop window fits its display's work area in logical pixels.
Every page centers one content column, `--content-width` in [tokens.css](../app/src/styles/tokens.css).
A workspace whose grid and preview use every pixel, the Images task in Guided and Assistant-led, is a wide [PageLayout](../app/src/ui/PageLayout.tsx) instead: it spans the window inside the gutter, and its frame rows widen with it so their edges keep lining up.
Frame rows (page headers, stage strip, task tabs, scrolling bodies and footers) span the window and pad their content to that column; rows that do not scroll reserve the body's scrollbar gutter, so every edge matches across screens and window sizes.
Windows 720px tall or shorter compact the top bar and footers; fill editors and file lists keep a minimum height, and the body scrolls instead of collapsing them.
One choice among a few, such as Batch or Live and the file-group filters, uses [SegmentedControl](../app/src/ui/SegmentedControl.tsx), so it reads as one choice rather than separate actions.
Editable suggestion fields use the shared [ComboBox](../app/src/ui/ComboBox.tsx): its top-layer list scrolls within the available window height and opens above the field when space below is limited.
Action lists that open from a button, such as the project switcher, the [model menu](../app/src/features/settings/ModelMenu.tsx) and Image Manager's Select and More, use the shared [Menu](../app/src/ui/Menu.tsx) in the same top-layer style, with arrow-key movement and light dismiss.
The model menu reads the connection's models only when opened and saves against a fresh settings revision; it refuses while Settings holds unsaved edits, and a clean Settings page reloads after it saves.
The same menu sits on the Settings connection panel, so the model is chosen beside the connection it belongs to; Translation defaults keeps the language and per-model options.
The list opens with a [MenuSearch](../app/src/ui/Menu.tsx) field focused, and Down moves into its matches; the field also takes a model ID the list lacks, offered as Use and taken by Enter when nothing matches.
Choosing a model saves it as the Settings default, which the feedback beside the menu says.
It retains typed values and keyboard selection without relying on the native datalist popup.
Keyboard focus shows the shared `--focus-ring`; pointer focus adds no outline, and text fields mark focus with their border.
A [Modal](../app/src/ui/Modal.tsx) opens with focus on its first control, or on a control marked `data-autofocus`, such as the chosen card; React's `autoFocus` runs before the dialog opens and is overridden.
Shortcuts come from [useShortcut](../app/src/state/useShortcut.ts), scoped to the visible screen and the top dialog: the save key saves the open editor and Alt+Left/Right move between Guided tasks; nothing that spends, applies or packages gets a shortcut.
ComboBox choice labels hide automatic text-selection highlighting while retaining select-to-replace search; typed queries and editable text keep normal selection behavior.
Sized dialogs use [Modal](../app/src/ui/Modal.tsx)'s `size` with [DialogHeader and DialogBody](../app/src/ui/Dialog.tsx) and an ActionBar footer.
Sheets and inspectors close with the header's one close button; decisions such as spending reviews, resyncs and Apply have no close button and end with explicit footer choices.
Reserve cards for content requiring a distinct container.
Use the shared [JobStatus](../app/src/ui/JobStatus.tsx) for operation summaries, including the Project page, so generic completion messages are handled consistently while useful detail remains visible.
Keep failures beside their action or in the run/file inspector; do not aggregate historical errors into page-wide reminders or counters.
Status colors always accompany text or icons.
Shortened file names use [FileName](../app/src/ui/FileName.tsx), which gives way in the middle and keeps the extension and the characters before it, where numbered names differ.
Editable folder and file paths use [PathInput](../app/src/ui/PathInput.tsx), which shows a long path's end while it is not being edited.
Read-only paths use [PathText](../app/src/ui/PathText.tsx): inside the home folder they start with `~` through [homeRelative](../app/src/ui/displayPath.ts), a long one gives way at the start, and hovering or copying it gives the full path; a review that confirms a destination wraps it instead.
Electron passes the home folder to the sandboxed preload as a launch argument.
Status marks come from [StatusIcon](../app/src/ui/StatusIcon.tsx) rather than text characters, so they keep their shape in every font.
Work items say where they stand in one vocabulary, the display states in [displayStatus.ts](../app/src/ui/displayStatus.ts): Not started, Working, Waiting, Needs review, Ready to apply, Applied, Done, Outdated, Blocked and Skipped, each with one mark.
Each feature maps its own states there and keeps its specific reason in the item's detail; backend state machines are unchanged.
Waiting means the work is with an assistant, never that the app is running something, and Done is finished work that never writes into the game.
[StatusMark](../app/src/ui/StatusMark.tsx) shows a state on its own and StatusHeading leads a list row with it; other states, such as a connection check, may use a mark directly.
Inline notes use [Notice](../app/src/ui/Notice.tsx): neutral notes, including empty states, read as plain secondary text, and warnings get the warning edge with their way forward beside them.
Disclosures share the app's chevron marker and hold genuine advanced settings or long evidence, not status the task already needs.
Saved results, worker logs, frozen scope and record identifiers belong to the inspector's Technical view rather than routine run views.
Action controls pair the shared pending button and status feedback with `useAction`'s guarded action key.
Toolbar controls use its inline presentation: pending text replaces the label, and result feedback appears once beside the action.
A row of related inline steps, such as Image Manager's discovery steps, shows their one result after its last control, so a result never moves the button just clicked.
Inside action bars a control's result or disabled reason sits just left of its own button, so buttons keep their place and the bar keeps its height.
A long error shows a short excerpt with Show more, and the expanded text scrolls within a bounded height instead of growing past the page.
Successful operations that finished before the interface loaded stay in History rather than beside their control; failures remain until a newer attempt replaces them.
An action error clears when the user edits the draft it ran with.
Tertiary actions inside running content use the `link` button variant, whose label aligns with the surrounding text; `quiet` buttons belong in toolbars, headers and footers, where their padding is the hit area.
Saved operation indexes carry their action identity so feedback can remain beside the correct control after navigation or restart.
A control given its `feedbackKey` registers with the nearest [FeedbackOwners](../app/src/ui/FeedbackOwners.tsx) scope, so a page's fallback message shows only errors that no mounted control reports.
Repeated label/action rows use [ActionList and ActionRow](../app/src/ui/ActionList.tsx): a `title` and `description` label (or a custom `label`), wrapping text, and a stacked layout based on available container width.
A list is one bordered panel with dividers, so each row's actions sit beside the text they belong to; actions keep their natural width at the row's end and stack below the label in narrower containers.
The compact variant drops the panel for dense lists that already sit in a container or style their own rows.
Tables, editors and the image grid stay unboxed.
Rows grow with feedback rather than fixing heights or clipping content.
Staged preparation requires existing game JSON at preview and execution; missing Ace exports cannot count as completed formatting or authorize a new baseline.
The engine's [JSON](../backend/dazedtl/engine/util/dazedformat.py) and [`plugins.js`](../backend/dazedtl/engine/util/project_preparation.py) preparation formatters write UTF-8 with LF on every platform, matching translated JSON and fitting output.
Byte comparisons normalize already-formatted CRLF/CR files too, preventing whole-file line-ending diffs on Apply.
Frozen outputs and exact backup/restore bytes remain authoritative.
Formatting, GameUpdate creation, initial source backup, the version baseline and local estimation consume a preview immediately after the user's click; the same backup, project ownership, input validation, and one-use execution checks still apply.
Replacement backups, paid work, runtime replacement, and file resync retain their review requirements.

Translation follows the working Qt GUI's task order through the tasks in [workflow.ts](../app/src/features/guided/workflow.ts), grouped into five stages: Set up, Context, Translate, Check and Release.
A stage holds the tasks that share its purpose, so no stage exists only to host one optional workspace.
Saved positions use the stage ids `setup`, `context`, `translate`, `check` and `release`; the backend's [retained_position](../backend/dazedtl/translation/guided.py) and the [navigation preferences](../app/src/app/navigation.ts) map the seven-stage ids and retired tasks to the task that holds their work, and Apply & Fitting's last view becomes its Check task.
Required and optional tasks are marked in workflow.ts; optional work never holds up the next step.
The app sidebar stays global; every phase uses the same one-row stage strip, which compacts when narrow.
The Translation screen has no header row; the top bar holds only the project switcher and app status.
One task occupies the editing body and its action footer stays outside the scroll region.
One copied setup task identifies speaker formats, runs local name collection, then uses those results for the glossary/context investigation.
Guidance review and layout settings follow before the named database and dialogue actions.
Phase navigation restores the last available task saved for that project, falling back to the phase's first task when an engine-specific or removed task is unavailable.
Every phase with multiple tasks uses the same clickable task tabs, with completion marked after each label and optional tasks marked until done; views inside one task (the Other event text steps) use secondary tabs below them.
Every task starts with the shared [TaskHeader](../app/src/features/guided/workspace/TaskHeader.tsx), whose title and description a task view may override, and its footer starts with Back and reports only that task's own state.
Plugin files and Images host their full workspaces as the task body (Images is the shared [Image Manager](../app/src/features/images/ImageManager.tsx), with no separate screen or summary page) and fill the Guided footer slot with their own ActionBar, still starting with Back and ending with Continue.
The stage strip is a stepper: each stage's number sits in a circle that turns accent once a task is done, fills with the accent while the stage is current, and becomes a check when its required tasks are done; the Project page's Status holds the full checklist.
A stage of optional tasks only, such as Check and Release, is done once the user has opened it with every required task before it done, because looking at what it offers is all it asks; its tasks keep their own marks.
Opened stages come from the saved navigation positions, so this needs no separate record, and the required-task condition keeps a stage opened early from reading done on an untranslated game.
Tabs and Continue retain drafts and allow navigation regardless of task completion or stale investigation status; they do not save review receipts or complete skipped tasks.
Status checks remain at execution and explicit save boundaries.
Release shows the backend's selected unapplied-output list and directs the user to Apply before enabling packaging.
Each saved ZIP records the size and modification time of the runtime files it was built from, ignoring device, inode and change time, which metadata updates such as permission changes also alter; a later difference or a newly applied image marks it outdated, and archives saved without that record are not compared.
Its destination fields are checked as they change through a read-only call to the same rule packaging enforces, so Build stays disabled with the reason instead of failing late.
Explicitly declined speaker preflight is interpreted as canceled only with verified first-attempt, no-submission evidence and no saved outputs or queue artifacts.
Historical affected jobs retain their stored records; canceled retries reset their progress phase so a later provider failure cannot inherit cancellation.
Other failed, stopped and interrupted paid runs keep their project ownership and recovery receipts.
Setup investigation may inspect narrowly relevant font, window-skin or image geometry for layout, while image inventories and editing belong to Images.
Context uses compact Names & glossary, Guidance and Line widths tasks.
Names & glossary shows one row per saved artifact with a consistent Saved label, plus the actual state of a running or failed local scan.
The shared observer updates saved results and guidance without a separate refresh action, and so do Other event text findings and Text QA findings; Image Manager keeps explicit refreshes because importing a saved image report validates it first.
Reference game folders are retained per project by [reference_folders.py](../backend/dazedtl/translation/reference_folders.py) and included as read-only source material in the copied investigation prompt.
Adding a folder only registers its path; it does not parse, convert or index the game.
Missing references remain listed so they can be removed or replaced.
Earlier native reference imports and their translation matching remain intact.
Translate task 3, Other event text, retains investigation, source choice, translation and comparison views within one task.
Its [investigation contract](../backend/dazedtl/translation/event_text.py) binds findings to selected event files, original data and plugin dependencies, and installed parser definitions.
The assistant applies a current report through the project helper's `event-text --apply`, and Use recommendations does the same in Source choices; either saves the recommendations and the consumed report ID in one write, and running work or a pending option draft refuses it, as for speaker findings.
Mixed or uncertain recommendations stay off; source choices need no separate review, and each frozen run records its source settings and report.
Code 122 requires explicit starting IDs, registered 357 and 355/655 selectors use exact installed identifiers, and 356 remains a single coarse switch.
The compact selectors retain searchable, grouped drafts separately from saved engine settings and preserve hidden selections.
The comparison cache is literal-based and requires a matching coverage review; missing, malformed and nonmatching caches expose distinct continuation or recovery states.
New guided projects select all supported files, clear inherited advanced targets and start in Batch only when the active connection supports it; existing projects and frozen runs retain their choices.
Applying and testing a small scope is available before expanding translation.
Speaker findings use the structured contract generated by [speaker_setup.py](../backend/dazedtl/translation/speaker_setup.py).
A copied setup task binds its report to this project and request.
The app verifies source hashes before enabling only confirmed, high-confidence rules; prose reports and partial, stale or foreign findings cannot configure options.
The agent's scoped `speakers --scan` helper applies the rules and launches the preserved parser's scan phase in an isolated worker without credentials or network access.
It never translates names; literal nameplates and the native actor/variable lookup tables feed the rest of the setup investigation.
Preferences and the consumed report are saved atomically through the compatibility boundary.
Pending option drafts and actively running workers defer application; dormant API runs do not block speaker setup or local scanning and retain their frozen settings and receipts.
The shared observer reports scanner results; manual overrides survive new findings until explicitly reset.
Copying another investigation task retains already-applied findings until replacement results are saved.
Scan availability is checked against the saved artifact and its owning operation separately from current source/settings freshness.
Settings changes, another running scan or a failed rescan keep the previous verified saved names visible; only a current result can satisfy the assistant's scan-reuse check.
Guidance setup is complete when the glossary, style and game-context files exist in the game folder, including empty files.
Edits, drafts, scan freshness and old investigation records do not revoke completion.
No document review or conflict receipts are required; the optional context findings record supplies measured layout recommendations only.
The guidance editor keeps glossary, translation style/quirks and game context in separate tabs, with custom guidance available in its file toolbar.
The selected tab is retained per project, and legacy glossary/voice review positions open the corresponding tab.
Missing custom files remain addressable while their recovery drafts exist.
Switching tabs and continuing retain drafts.
Explicit Save writes the editor's guidance over the current files through the native serializer, creating missing core files without an empty-document approval.
It reports successful writes if a later document save fails and retains remaining drafts.
Guidance has no revision-conflict workflow; paid estimates still bind the actual saved inputs used for translation.
The shared plain-text editor retains glossary category headers, source (translation) entries and same-line notes; engine parsing and per-batch selection remain unchanged.
Measured layout values are saved automatically when their project-bound report and source evidence are valid.
The observer and project helper use the same reconciliation, deferring writes during active work or pending option edits.
Each report is consumed once; later manual widths are retained until an explicitly requested new measurement establishes a new baseline.
Late recovery writes rebase across this layout-only change without losing manual edits.
A failed automatic save is held for an explicit retry rather than repeated by polling.
Defaults remain identified separately, and remeasurement is optional.
Saved findings describe the investigated source; translating runtime files does not erase that record.
New projects also clear inherited optional speaker rules.
Set up is one task: its form takes the version and the explicit untranslated/original-source choice, retained in the Guided form, and one action runs the untouched backup, file preparation and version baseline in sequence.
The [workspace hook](../app/src/features/guided/workspace/useGuidedWorkspace.tsx) runs each step through its own preview and execution and waits for the observed operation and an idle backend before the next, so every step keeps its checks and receipts; a replacement backup keeps its review and the sequence continues once it is approved.
A failed, stopped or declined step ends the sequence with its reason beside the action; the next click resumes from the first step that is not done, and projects set up before this keep their saved backup and baseline.
The original-backup record lives in the profile's per-project lifecycle, while snapshots stay portable in the game's own store, so a moved or copied game opens without a record although its store holds the original.
Translation state then offers the earliest game snapshot there, which setup saves first, and the backup step takes it over (`use_source_backup`, bound to the snapshot it showed and refused once a record exists) instead of saving the current, possibly translated, files; saving the current files instead keeps its review.
The preparation worker records each completed stage against the current prepared files, stops on failure or cancellation, and resumes remaining stages without repeating current completed work.
Individual preparation tools update the same receipts; GameUpdate file installation does not imply a tested delivery configuration.
New baselines require current preparation evidence at preview and execution; existing Git baselines remain usable without historical preparation receipts.
A finished setup continues to speaker/context setup only after the saved operation and baseline are confirmed, without starting an assistant task.
Recovery and official-version updates are project utilities, outside the normal preparation sequence.
They are the Project page's Game updates and Backups tabs, whose primary actions use the shared [ActionSlot](../app/src/ui/ActionSlot.tsx) to stay in the tab's footer while content scrolls.
The update view shows one current preparation/comparison at a time; a later attempt or changed Git state prevents an old comparison from being offered for application.
Guided keeps update steps in History's other activity, so the view lists no second history and its comparison omits the saved result; a failed step without its own control appears beside the interrupted-update recovery.
Backup history is grouped by game versus project files and appears only after the user chooses recovery.
Navigation never completes a task.
Prepared originals are summarized; recent activity holds saved history, while active work and required approval remain visible across areas.
Assistant task controls describe the expected return and report only copied instructions or saved findings, never an external process inferred from a click.
Every task that hands work to an assistant (Names & glossary and line width measurement, Other event text, Plugin files, Images, Text QA and Assistant-led) shows the shared [AssistantTask](../app/src/ui/AssistantTask.tsx) panel: where the task stands, in the shared display states, what comes back, and a row per expected result.
It is a [StatusPanel](../app/src/ui/StatusPanel.tsx), the panel any work that is not the user's own uses to show its name, state and next step, such as Assistant-led's API run.
The panel reads Needs review only while a result waits for the user's decision in that panel; a result that saved itself reads Done, or Applied once in the game, and one waiting only to go into the game reads Ready to apply.
Findings that inform a later step read Done once saved, and that step holds any choices they leave, as Other event text's Source choices do.
Outdated marks a saved result whose basis changed before it went into the game; edits after a task's result is applied are expected and leave it as it was.
Other event text findings applied as source choices therefore stay current until the selection reaches event files they did not cover or the installed parser definitions change, a plugin file with nothing left to apply keeps its state until a copied task rescans every file, and Text QA reads Applied once corrections chosen from its own task are applied.
The task's main copy action stays in its footer; optional companion tasks, such as layout measurement and the running-jokes investigation, keep theirs on their result row.
Each copy reply names its handoff: the task's kind, request id and the result files it expects back.
The [Application](../backend/dazedtl/api/server.py) records it in the [assistant task registry](../backend/dazedtl/translation/assistant_tasks.py) and strips it from the reply, so features keep their own requests, reports and validation.
The snapshot lists the records with the newest time an expected file was saved, read from file times only, and [assistantTasks.ts](../app/src/features/assistant/assistantTasks.ts) derives each task's display state from that and its feature's observed state, so the Project page list, the top-bar count and each feature's panel agree.
Dismissing marks a record abandoned: the task leaves the list and its feature stops showing Waiting until the next copy, while saved requests and reports stay.
Tasks copied before records existed list only while their feature still waits; the running-jokes investigation saves no checked result, so it is not tracked and its row shows no state.
Output availability, application to runtime files, assistant QA findings, and package availability are separate observations.
Execution rechecks source, scope, destination, and ownership evidence.
Application receipts distinguish later fitting or QA edits from new outputs that have not been applied.
Release plans bind the profile's working-source index and original blobs; refreshing or expanding a source pass invalidates pending package plans without rewriting old runs.

Check's Line width check and Text QA tasks share retained file choices and check settings.
Each task applies its own work and shows what it has not applied; no cross-task list reminds the user of skipped work, because the stages and tasks already show it.
Text tasks and Release apply saved output through the Guided action review.
The Review & apply buttons in Plugin files, Line width check and Text QA, and Images' Apply to game, open one [PendingReview](../app/src/features/guided/workspace/PendingReview.tsx) of their part, whose content reuses that part's own review; Assistant-led's Image Manager keeps its own review.
Its [hook](../app/src/features/guided/workspace/usePendingChanges.ts) prepares the part's preview from observed state through [pending.ts](../app/src/features/guided/pending.ts) and applies it under one action key, so a repeated click cannot start it twice.
Image and plugin parts execute their own one-use tokens; the Guided review keeps one preview at a time, so rewraps and QA fixes are previewed again just before they execute and refuse to run if the bytes they would write, compared by hash, differ from what was reviewed.
Images restore in the Image Manager and plugin files in their workspace; applied text batches have no restore of their own, since Git version tracking and Backups undo them.
A text batch whose publication was interrupted or could not roll back raises a notice on every Guided task with its Review restore, because part of it may be in the game.
TL Inspector and Forge install from a Playtest tools sheet in Check's task header, where applied text is playtested, and an Ace game's native packing sits in the same header; both reuse the Guided action reviews and operation tracking, and the Project page stays about status, history, updates and backups.
The player walkthrough task sits with Release, since it produces player documentation.
The [text publication journal](../backend/dazedtl/translation/publication.py) freezes reviewed destinations and both byte versions before any runtime replacement.
The compatibility worker reuses the engine fitter on disposable copies, then preflights and publishes the whole batch with verified backups and rollback attempts.
Interrupted publication retains exact authorized before/after hashes for another reviewed restore; conflicting newer runtime edits are retained.
Completed restores retire the recovered batch's notice in history; undoing a restore revives the earlier batch state without changing preserved receipts.
Reapplying saved translations discloses replacement of later runtime edits, independently of output availability.
Optional text QA retains the engine's project-scoped discovery inventory and findings, bound to current runtime text and original-source context.
Copied tasks do not imply completed work, and a saved discovery stage does not certify current QA passed.
Chosen corrections bind to the specific task and pass the engine's correction and regression checks on disposable copies before app-reviewed Apply.
The clipboard task stops before runtime publication.
QA and opening the game are optional, with no playtest records or QA prerequisites for navigation or Guided Release.

The selected phase files bind each new run and each application preview.
Working copies are prepared automatically without removing other phase work.
The compatibility launcher filters the preserved phase's selected files, retaining its profiles, glossary, speakers, and frozen run format.
Working copies are seeded from current game bytes and are retained across navigation, estimates and restarts.
Original-branch/native-original identities remain reference and recovery bindings; they do not force working copies back to untranslated versions.
Resync is a repeatable, reviewed replacement of the checked files with their current game bytes.
It archives their working copies, staged outputs and variable cache first.
Frozen Live and Batch workers can continue; their results remain in History.
Tool writers serialize with resync, workspace collection pauses during replacement, and new translation preparation waits until resync finishes.
Per-file versions advance before replacement so earlier runs cannot overwrite resynced files or supply stale cached responses, even if resync is interrupted.
A handled write failure restores the previous files and versions.
Other files keep their progress; frozen run outputs remain inspectable under their original project owner.
The former manual screen remains a compatibility route into Translation, preserving saved project identity.

### Navigation and responsiveness

Project identity, execution mode, and visible screen are separate.
Registry upgrades retain existing IDs, backend job references, phase selections and recovery data when adding workflow screens.
Portable workflow options live in the selected game's .dazedtl/len-method/workflow.json; the old Len project.json is imported without being overwritten.
The app profile holds connections, recoverable drafts, run plans and receipts, and older full-copy backups.
New source/workspace snapshots live in the game's .dazedtl/backups/v2 store.
Source guidance remains in the established game files.
`useApplication` supplies shared state through one observer; feature polling loops would introduce competing reads.
The application provider supplies its API and browser event subscriptions; the observer owns response ordering and refresh scheduling.
The shared [navigation state](../app/src/app/navigation.ts) owns the visible screen and per-project workflow views independently of backend observations.
Existing screens switch from already observed data after draft leave guards finish; a background read cannot move the user back.
The shell starts at the Project page on launch or project selection.
Workflow tasks, document tabs and event-code views are small browser-profile preferences, written before the view changes; older backend positions supply the fallback until local preferences exist.
These preferences contain no game text, drafts or execution authority.
The first entry into an uninitialized Guided workspace still links it through the backend.
Task Options panels configure the task in place; they must not act as navigation menus to other phases.
Keep cross-task navigation in the phase/task controls, and reuse settings controls inside the owning task’s panel.
Route application screens and Guided workflow locations through the shared navigation methods exposed by `useApplication`; keep feature-local view choices in their owning UI state.
Switching an already-loaded view with clean drafts must not require a Python request or await a project snapshot.
Retain usable page data across revisits where its ownership and invalidation rules permit; scope any missing-data load and its pending feedback to the feature that needs it.
[App](../app/src/app/App.tsx) and the [Guided workspace hook](../app/src/features/guided/workspace/useGuidedWorkspace.tsx) provide working examples.
Automatic refreshes yield to the next operation in a chained action, so saving a draft and then navigating does not insert a discarded project read between them.
Use `application.settle` for `useAction` completion that needs updated observed state: it waits only when an API mutation invalidated that state.
Reserve `application.refresh` for an intentional re-read, such as an explicit reload control.
Views that show their own replies before the next observation, such as Plugin files and Image Manager, use [`useObserved`](../app/src/state/useObserved.ts): a newer snapshot replaces a reply during render but waits while unsaved edits or actions build on the current revision.
They start from the observed state when the snapshot already has it, so revisiting them reads only what is missing.
Do not attach an unconditional whole-project refresh to every button.
An open project stays observable while no app worker is active so external assistant reports become visible.
Returning to the window rechecks outside edits through `workspace_recheck`, which reinspects the images being worked on (working copies, the selection and applied images) against their cached file signatures; as a mutation it is followed by a fresh observation, so every feature sees the result without its own refresh.
It also imports a report saved for a copied image task, including a finished task's report the assistant saves again for the user's redo requests, and the Image Manager runs the same import every few seconds while a task waits, so results arrive while DazedTL keeps the focus; a rejected report is remembered by its hash, so it is reported once and retried only after the file changes.
Guided reports are read by the observer, and plugin reports are validated by the project helper's continue command the assistant runs.
Saved run indexes keep these observations small; full request bodies are checked at execution/inspection boundaries.
New observation work must use bounded summaries or cached derivations with explicit invalidation.
Do not add whole-game parsing or full request-history reconstruction to a polling snapshot.
Measure nontrivial additions with representative generated data; keep authoritative source, artifact and spending checks at their execution or explicit inspection boundaries.
Cached display state never authorizes paid work or file publication.
Each Guided observation reuses ownership, run metadata and name-reuse reads within that observation.
The bounded [history display cache](../backend/dazedtl/compatibility/observations.py) retains compact plan headers and process summaries across observations.
Plan hashes, in-memory job state, and artifact metadata invalidate those summaries, including new/deleted queue fragments, clarification receipts, output files and SQLite journals.
Files changing during a read are not cached.
Imported Batch roots use fresh readers.
Execution and explicit inspection bypass this display cache and retain their authoritative checks.
Variable-comparison observations retain only parsed literals bound to the current file content; mappings, selection, settings and review are reconciled on every read.
Translation preparation follows the matching estimate through this same observer, showing its completed-file count and last checked filename.
Estimate startup, finalization and Live/Batch cost-review preparation have distinct feedback; cancellation and late observations cannot advance to another request or approval.
Backend disconnection invalidates pending reads so a late response cannot restore an obsolete connected state.
`useAction` guards duplicate submissions, while `useDraft` serializes recovery writes and explicit saves.
Recovery drafts remain dirty until committed; leave guards flush them before navigation and close.
Autosaving editors, such as Image Manager and the image text editor, save every write instead, so a successful write becomes their clean baseline.
Mutations changing snapshot-backed state, including recovery drafts, must keep the default `refresh` in their [method contract](../backend/dazedtl/api/contracts/methods.py), so remounted editors cannot recover an older draft from the cached snapshot.
Guided engine options use the same draft session and retain the native revision check.
Setup-form recovery lives alongside project records in the profile.
Opening Guided transfers any pending shared-context draft before linking the native workflow.
Never retry writes automatically, since some actions submit paid work.
Task and screen error boundaries isolate render failures from navigation and the application observer; the root boundary provides a final recovery surface.
Explicit retries and interface reloads flush retained draft guards, including failed writes from unmounted editors, before remounting.
Plugins is bundled with the other screens so rebuilding the desktop app cannot remove a deferred chunk still needed by an open window.
Electron owns the native renderer-crash/unresponsive dialog and reloads only on explicit user choice, keeping the existing Python process and job ownership.
Forced renderer replacement bypasses unavailable draft saving only after explaining the possible loss.
Renderer diagnostics contain fixed error types and source locations resolved through the build's hidden source maps, never exception messages or raw stacks.

### Persistence and settings

Project-format changes increment `SCHEMA_VERSION` and register consecutive upgrades in [projects/store.py](../backend/dazedtl/projects/store.py).
The storage helper validates the result, retains the original bytes in a backup, and replaces the file atomically; unsupported or invalid formats are left untouched.
Project opening and selection publish their in-memory ownership only after backend persistence succeeds; presentation-only navigation does not change that ownership.
Engine-owned settings and run formats remain the adapter's responsibility.
Diagnostics record only fixed metadata and relative code locations, excluding exception messages, payloads, and raw stderr.
They keep only failures the interface reports generically (internal and storage errors, abnormal backend exits, renderer failures), so explained refusals, clean shutdowns and relayed backend errors cannot push them out of the bounded report.
The report names the checkout revision and whether tracked files changed, since code locations resolve only against that revision.

Connections and preferences share one atomic record in workspace `settings/settings.json`.
The Settings editor retains its session while hidden, so returning preserves its current view and fields without another initial settings read; the sidebar marks Settings while that hidden draft is unsaved.
Saved secrets never enter renderer responses or recovery drafts, and model drafts are bound to connection IDs.
The public preference schema contains language, model, and per-model request/pricing options; legacy formatting and other engine values are retained privately through a backed-up versioned upgrade.
The adapter materializes legacy settings only before engine actions and checks the original provider route before resuming saved runs.
Connection checks are model-list requests, with bounded reads, no redirects, and no generated text; Settings runs one after saving new or changed credentials, and again on request.
Provider presets declare their transport protocol independently of their identity.
OpenRouter keeps the OpenAI-compatible Live request format and has a distinct [Batch transport](../backend/dazedtl/compatibility/openrouter_batch.py), layered onto the engine's Batch provider points.
Both Guided workers and compiled plans use that adapter, preserving request semantics.
The authenticated `/models/user` check retains a bounded, private [catalog](../backend/dazedtl/settings/openrouter.py); saving a model, host or active connection automatically resolves missing matching Batch endpoint capabilities and prices outside the application lock, then retains them within the same settings mutation.
Model-option reads resolve draft selections without changing saved Batch eligibility.
Matching saved endpoint checks are reused; late replies recheck the connection, credentials, model, host and authenticated catalog before publication.
Public listings never establish account eligibility.
Explicit model-option and estimate preparation actions can load missing or stale public Live prices outside the application lock, including host endpoint variants.
A bounded session cache binds those prices to connection, model and host; a late response rechecks the selection before publication, and a new authenticated catalog invalidates earlier public quotes.
Observations only read cached metadata.
Price lookup stays a read-only operation, so it cannot hold navigation behind a pending mutation; connection checks invalidate shared observations.
Existing custom connections and frozen runs retain their original identity and route.
Runs resolve credentials by the connection's recorded runtime name, so removing a connection strands its unfinished runs; removal takes the count the user confirmed, refuses it when the backend's recount differs, and rematerializes engine settings so the key leaves the derived cache.
OpenRouter connections optionally pin a host.
The editor loads the selected model's bounded public `/models/{author}/{slug}/endpoints` list without credentials, state refresh, or the engine context lock; requests and late results stay scoped to that model's picker.
A bounded session cache retains model-specific suggestions across editor and tab revisits until explicit refresh.
Endpoint variants collapse to a host slug, and the shared ComboBox bounds the read-only selection popup to the viewport.
Missing models never load the global list, and a saved host absent from new results remains visible without silently changing it.
Host selection joins the compiled configuration and Guided worker's frozen request policy before estimate/review hashing.
The shared [request adapter](../backend/dazedtl/compatibility/request_parameters.py) merges OpenRouter's `provider.only` and disables host fallback in the SDK body; saved runs without a host retain automatic routing.
The Batch transport lifts the same host into the batch header before its requests array and rejects mixed hosts before submission.
Changing the connection's host cannot redirect a resumed run.
The public list is advisory and does not establish account-specific eligibility or pricing; [OpenRouter setup](user-guide.md#openrouter) describes the control.
New OpenRouter runs freeze `openrouterStructuredOutputs` in both compiled configuration and Guided policy.
The [request adapter](../backend/dazedtl/compatibility/request_parameters.py) supplies the existing source-ID or LineN schema with `strict: true`, including for DeepSeek routes.
Live adds `provider.require_parameters`; the engine's [`STRICT_STRUCTURED_OUTPUTS`](../backend/dazedtl/engine/util/translation.py) setting disables native schema downgrades while preserving error metadata and existing validation.
Batch accepts only `provider.only`, so connection checks retain schema-capable endpoint tags and conservative rates across that set; the immutable Batch policy freezes both, and the transport rejects weaker schemas or changed endpoints before submission.
Google batches split when schemas differ, before the existing submission journal.
Saved policies without this setting retain their original parameters and fallback behavior.
OpenRouter's absolute Batch input/output and optional cache rates, host, transport version, and local request/byte split limits join each immutable plan.
Its [pricing adapter](../backend/dazedtl/compatibility/openrouter_pricing.py) adjusts estimates and native file accounting from the frozen rates without applying the engine's generic Batch discount twice.
The native OpenAI token window remains OpenAI-only.
Other providers' compatibility pricing resolver runs without credentials, reuses the preserved pricing rules, and labels cached catalog versus built-in rates.
The OpenRouter adapter uses ordered inline submission and stores terminal response evidence under the owning run before validating request IDs.
Verified responses can be collected again without provider access; incomplete or conflicting mappings cannot create a fetched marker or trigger paid retries.
The existing approval journal, monitor, ownership guards, and clarification allowance remain authoritative.
Unsupported cancellation is enforced in both backend operations and public capabilities and identified beside active Batch status; stopped queues retain provider receipts.
Terminal result loss produces persistent blocked feedback and an explicit collection retry instead of an automatic consume loop.
Provider-reported charges are retained independently from token-based estimates.
[OpenRouter setup](user-guide.md#openrouter) describes the user-visible limits and recovery controls.
New manual plans freeze resolved request size and base rates before hashing; small worker wrappers apply this policy before the native engine imports, including per-file workers.
New API configurations and native worker policies also freeze `maxOutputTokens`, resolved from the [general output default](../backend/dazedtl/settings/preferences.py) or per-connection/model override and any lower known model/host limit.
The override uses the existing serialized preference drafts.
The pricing metadata reader retains exact model output limits without borrowing a limit from the engine's fuzzy price fallback.
Custom pricing can reuse cached limits without adding an observation-time network read.
The shared [request adapter](../backend/dazedtl/compatibility/request_parameters.py) applies the frozen budget to OpenAI-compatible and Anthropic payloads and the native late Mistral override.
Live, Batch and speaker requests share that policy; prompt construction, reasoning defaults and parser behavior stay unchanged.
Missing fields retain the native budget when reopening older plans, so new defaults never reinterpret approved requests.
The optional per-connection/model `batchInputTokens` override resolves to the [application default](../backend/dazedtl/settings/preferences.py) for new OpenAI runs and joins the frozen policy and compiled plan configuration.
The Settings response exposes that same default for display.
It leaves 20% headroom below the published Tier 1 [GPT-5.5 Pro](https://developers.openai.com/api/docs/models/gpt-5.5-pro) Batch queue allowance, which is lower than the published [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) and [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) allowances.
This is a conservative fallback rather than an account quota: older models can have lower limits, GPT-6.1 Sol's public page does not currently list its Batch limit, and other pending jobs share queue capacity.
The [worker adapter](../backend/dazedtl/compatibility/worker_policy.py) supplies the frozen value to the Guided OpenAI Batch window as a combined active-token allowance.
Clarification batches reserve from that same allowance before recording submission intent.
Account usage outside the tracked Guided runs still needs headroom; the local estimate is not a provider quota lookup.
Older preferences need no rewrite, and older runs retain their native default or saved sequential limit.
[API setup](user-guide.md#api-setup) describes where to override it.
Existing plans without a policy retain their original behavior; provider cache and batch adjustments remain in the engine.

## API changes

The [Python contracts](../backend/dazedtl/api/contracts) define every method's parameters, reply shape and flags once.
Change a method there, in its handler and in [client.ts](../app/src/api/client.ts), then run `node scripts/contracts.mjs`.
It generates the renderer's [contracts.ts](../app/src/api/contracts.ts) and the [protocol manifest](../backend/dazedtl/api/protocol.json) read by Electron and the project helper; the build fails while either is stale.
The protocol version is a hash of the contracts, so any change rejects a stale renderer or helper before mutations execute.
Replies pass through the [public views](../backend/dazedtl/api/views.py), keeping legacy records behind that boundary.
Contracts are closed: declare what the renderer and helper may read, and drop what they should not.
Only records the backend keeps for its own recovery, such as the Assistant-led lifecycle and compiled request context, stay open beyond their documented keys.
The [contract test](../tests/test_api_contracts.py) checks every handler's parameters against its contract and validates replies from an offline journey.
Launch with `DAZEDTL_CHECK_CONTRACTS=1` to validate every request and reply while developing; a mismatch fails the call.
Methods refresh the workspace snapshot by default; permit close-time operations only when required to finish saving or reading.
Contract checks are a development aid; domain operations remain responsible for input validation and ownership checks.

## Translation execution and the agent boundary

The generated starting prompt uses scripts/project.py against an authenticated loopback endpoint in the running backend.
The connection descriptor is local to the profile, permission-restricted, and removed on shutdown.
Its token is never embedded in a handoff.
Agent operations use the same locked dispatch and project/run ownership checks as Electron; the helper has no settings or general shell endpoint.
The app controls its workers.
External assistant activity is reported from saved artifacts and must not be represented as an app-owned process.

A compiled plan freezes sources, full context, field constraints, provider parameters, rates, and connection identity.
Tracked game-source dependencies bind to their original-branch blobs; untracked source exports, project guidance and the plan file bind to their exact bytes.
Both API transports consume the same logical request builder.
Request IDs, speaker/scene context and protected tokens survive adapter conversion.
Version-two source plans require per-line text types and explicit nullable speakers.
Unknown speakers remain valid; only explicit source ambiguity notes create targeted review flags.
Classification and notes enter the same context/fingerprint in every mode.
Existing unversioned plans are accepted only when validating saved runs.
A compiler update may resume them when the complete logical requests and provider payloads still match; frozen plans and approvals are never migrated in place.
Accepted results are keyed by logical source/context rather than Japanese text alone.
Location hashes do not change their identity.
Explicit corrections retain history, require the current result hash, and invalidate affected review/injection/QA evidence.

Submission intent is durable before provider calls, and raw receipts are durable before acceptance.
SDK-level paid retries are disabled.
For compiled agent plans, an uncertain submission blocks overlapping work; Guided fresh-run review follows the separate policy above.
Attaching a provider job still requires matching returned request IDs.
Approval receipts bind the project, immutable plan and quote with a profile-local signature.
A saved boolean alone cannot authorize a worker.
Workers hold per-run locks and stop issuing work after losing their owning process.
Closing or pausing cannot undo an already submitted provider request.

Git baselines and backup records gate new translation work.
A checkout off the translation branch, or with an unfinished Git operation or asset sync, refuses every change to the game; [checkout_issue](../backend/dazedtl/translation/operations.py) names the problem for both the refusal and a translation warning that every Guided task shows.
Reviewed runtime manifests control patch scope; all .dazedtl work stays outside both branches.
The MV/MZ writer retains source metadata on ordinary corrections.
The explicit rebase route proves its source matches a reviewed original-branch blob before rebuilding metadata for a new source version.
Official update operations reuse the existing preview hashes, conflict recovery and native-byte rules.
New originals are staged separately for engine preparation.
A local delivery packages only reviewed Git files.
Public publication remains a separate action.
Guided rewrap application also requires a matching completed scan.
Ace preparation runs in Python on every platform: `util/ace` ports RV2JSON 1.2.1 and RPGMakerDecrypter's archive reading instead of shipping their Windows executables.
The port writes RV2JSON's JSON and Ruby 3.4's Marshal bytes so games and existing `ace_json` exports read the same; it departs only where RV2JSON broke games or hid text: it finds data files in any case, keeps Change Vehicle BGM audio as objects and adds the equipment type names to `System.json` as `equipTypes`.
[The Ace fixture](../tests/fixtures/ace/regenerate.py) records RV2JSON's own output for synthetic editor-shaped data, so conversion tests need neither Ruby nor real games.
RGSS3 reads only the archive while `Game.rgss3a` exists, scripts included, and probes on a real game confirmed it ignores loose copies and rejects an archive without its scripts.
So Set up keeps an encrypted game's archive in `.dazedtl/ace`, where releases and Git never see it, and patches carry it rebuilt with the game's current files; the rebuild keeps the original header, order and keys, so it reproduces an unchanged archive byte for byte.
Ace Release requires a packing receipt bound to every current JSON input and its corresponding native output; fitting, QA or native edits invalidate it.
Guided checkpoint manifests derive translation-only additions from the registered original and saved source inventory, retaining previously tracked runtime assets when switching workflows.

## Backup storage

Both agent operations and UI checkpoints use translation/backups.py.
Each version-two snapshot is a complete path-to-content manifest with file sizes, permissions and empty directories; content-addressed objects are shared across original, prepared-source and workspace snapshots in the same game.
No delta chain or live-file hardlinks are used.
Snapshot identity covers file content, paths, modes and directories, so unchanged captures reuse a manifest.
Backup presentation checks manifest and payload availability instead of treating a profile reference as proof that its files still exist.
Each observation checks shared object directories and payload sizes once, without retaining availability across observations.
Electron opens only backup folders the backend returns as available.
Full content hashes are still verified at restore and reuse boundaries.
The managed store has its own writer lock.
Content is verified before reuse/publication; source mutations abort capture.
A failed capture removes only unpublished objects it created.
Existing snapshots are never pruned.
The project's `source_backup` record is the original it was set up from: a later game backup becomes `game_backup`, the latest one the Backups tab shows, and replaces the original only when that is missing or unreadable, judged before the new capture because an identical capture shares its identity.
Plugin lookup evidence and release original bindings read the original, so saving the translated game must not move it.
After a source backup is successfully saved, the operation reconciles profile references to a deleted workspace snapshot and engine investigation whose evidence files are all missing.
It archives those records under profile `backups/stale-project-records` before retiring them.
Read-only observations do not clear records.
Existing or unreadable artifacts, prepared-original baselines, and run history stay intact; a failed or cancelled backup does not retire anything.

Workspace capture excludes the entire .dazedtl/backups directory, including any pre-existing manual backups.
Source capture excludes .git and .dazedtl.
Arbitrary nested destinations remain forbidden.
The v2 subdirectory avoids repurposing existing backup folders.
Older version-one full-copy snapshots remain supported by the reader.
Engine operations obtain temporary verified normal files through materialized; patch checkpoints materialize only their runtime source paths.
No expanded cache is retained.
Restore verifies into a staging directory before publishing a new destination, refuses existing or overlapping targets, and reconstructs empty directories and file modes.
The independent scripts/backups.py reader can recover a moved game without its former app profile.
Restoring a workspace does not transplant connections, paid-job ownership or spending authorizations from another app profile.

## Distribution and updates

Users download the repository as a ZIP and run a START launcher; there is no installer or build pipeline.
The launchers only fetch the Node pinned in [runtimes.lock](../scripts/runtimes.lock) and checked against its published checksum, then hand over to [start.mjs](../scripts/start.mjs).
[setup.mjs](../scripts/setup.mjs) installs the pinned standalone Python the same way, creates `.venv` from it and installs the hash-locked packages and Electron.
Electron's binary is downloaded with its package's checksums but unpacked by [zip.mjs](../scripts/zip.mjs), because Electron's own installer extracts with a native module that needs the Visual C++ runtime, which a fresh Windows lacks.
Each step records its inputs in `.runtime/state.json` and reruns only when they change, so an update that changes a lockfile, a version file or the folder location repairs the install on the next start.
User installs omit the development tools; a Git checkout defaults to the development set.
npm comes from the pinned Node whenever it is installed, because the system Node may have none or a different version.
Translation projects are Git repositories, and Windows ships no Git, so setup installs Git for Windows' portable MinGit there, pinned in the same lock; other systems must provide `git`, and setup stops with the install command when they do not.
MinGit's system config sets `core.autocrlf=true` as a Git for Windows install does, which the engine's repo-local line-ending settings already override.
The launcher puts its Node and, on Windows, that Git first on the app's `PATH`, since the backend validates plugin scripts with `node` and runs `git`.
Detached launches log Electron's output to a temporary file and wait for its "shown" line, so the console stays open with the error when the app fails to start.
Shortcuts are written once per folder location, and a deleted desktop shortcut stays deleted.
Ubuntu's AppArmor rules block the Chromium sandbox of unregistered binaries, so the launcher stops with a one-time profile command instead of letting Electron exit silently.

A release is a `v` tag on every mirror in [mirrors.json](../release/mirrors.json), whose commit carries `release/manifest.json`, the SHA-256 of every tracked file, signed with Ed25519 in `release/manifest.sig`.
[update.mjs](../scripts/update.mjs) lists tags through each mirror's Git smart HTTP ref advertisement, which every forge serves the same way and without API rate limits, and takes the newest version any reachable mirror has.
An archive is accepted only when the signature verifies with a key from the installed `release/keys` and its files match the manifest exactly, so a compromised or stale mirror can withhold releases but never alter one.
The manifest hashes committed blobs, which is what forges archive; [release.mjs](../scripts/release.mjs) proves each tag against its own `git archive` before pushing.
The [update controller](../app/electron/updates.cjs) runs the updater in Electron's Node as a child process, so verifying an archive never blocks the window, and stages the files in `.runtime/update/next`.
The launcher applies a staged update before setup and before anything loads the files it replaces.
It backs up every file the swap touches to `.runtime/update/previous`, journals the swap, replaces changed files by atomic rename and removes files the release dropped, writing the manifest last.
A swap stopped by a crash finishes on the next start; a failed one restores the backup; Settings reports the outcome once.
After a successful swap the old launcher hands over to the new START launcher, so a release's own setup code and runtime pins apply from its first start.
Releases still keep `.node-version`, `.python-version` and the other files 2.0.0's launcher reads after its swap, since that launcher continues in place.
Files outside the manifest, such as `.venv`, `.runtime` and downloaded models, are never touched, and Git checkouts are left to Git.
"Restart to update" closes through the usual save handshake, refuses while a run is active, and relaunches through START with the app's switches, which waits for the old process to exit.
The backup also serves "Go back"; automatic checks skip the version the user went back from.

Every tracked path stays within 185 characters, checked by [paths.mjs](../scripts/paths.mjs).
Windows Explorer and Python stop at 260 characters unless long paths are enabled, and Explorer unpacks a GitHub ZIP into a doubled top folder.
The budget leaves room for an install folder like `C:\Users\<26 characters>\Downloads\DazedTL-2.0.0\DazedTL-2.0.0\`.
The same check rejects paths, and module names without their import extension, that differ only in letter case.
Windows treats such names as one file, so an import of `./GuidanceReview` loaded `guidanceReview.ts` instead of `GuidanceReview.tsx` and broke the renderer build.
When a clash needs a rename, rename the file whose old copy would be harmless, because a ZIP unpacked over an older install keeps files the release dropped.
