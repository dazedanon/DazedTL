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
Each workflow action is one row of the [action registry](../backend/dazedtl/actions.py), which says how it is reviewed and run and what its review and History call it; Guided's checks, the worker and, through the generated contracts, the renderer read it.
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

### RPG Maker text blocks

[rpgmaker_blocks](../backend/dazedtl/engine/util/rpgmaker_blocks.py) is the one definition of how MV/MZ event commands form the text one window shows: a message (101 and its 401 rows), scrolling text (105 and its 405 rows), a choice list (102), a choice's help and other comments.
A choice's help is a comment (108) right after a choice branch (402), whose 408 rows MPP_ChoiceEX shows while the choice is open; players read a comment's rows only under a marker a plugin shows, read from the plugin list the game loads beside its data folder, as JavaScript reads it ([rpgmaker_markers](../backend/dazedtl/engine/util/rpgmaker_markers.py)).
Translation, the fitter, Text QA's inventory, verifier and never-translated preflight, Assistant-led's writer and the release playtest all read blocks there.
The playtest's tour gets an index of them before it plays, so a message it sees and the line the static checks list share one identity, the block's first text row, and a message whose name alone was translated still reads as never translated.
A translated part keeps its Japanese in `_original` on its anchor and owns the rows its text was written over; rows outside the parts are the game's own, and nothing writes them.
Translation laid a comment one Japanese line at a time, and a game may follow those lines with its own, such as "(1/3)" or a blank spacer, so a comment's translation records the rows it owns beside `_original` as `_rows`, a note that game updates and Assistant-led's writer carry with it.
A message is one command once translation joins its rows, and Assistant-led's rows run up to the next translation, so they need no record.
Help translated before the record existed reads its rows against the original game file where the reader has it, as restoring a refusal note before a run does, and otherwise owns the rows after it that hold text and no Japanese, which is all translation ever wrote there.
Writers lay text over a block's rows and never add or remove a command, so a saved game's place in an event stays valid: scrolling text puts its lines over its own rows, and help that needs fewer rows than it owns moves the spare ones, empty, past the game's own rows to the end of the comment, stopping before a later translation, whose place Text QA and saved notes know it by.
Rows of a part that still hold one of its Japanese rows as the game wrote them, such as a page number Assistant-led left as it was, are the game's own and keep their row when the text around them is fitted.
Assistant-led keeps a comment's Japanese, marker first, on the 108; both forms read as one block.
Translating a comment never adds or removes a command, so saved games keep their place and Assistant-led's `rebase_rpgmaker` still lines up: the lines go over the rows it owns, extra lines in its last row, and rows it no longer needs move, empty, to the end of the comment, where they show nothing.
Translation still joins a message's 401 rows into one command on the first pass, as it always has.
Help wraps beside the face of the message its choice follows, even while the engine has emptied that message's joined rows, and keeps the rows of the Japanese list items ([wrap_help](../backend/dazedtl/engine/util/rpgmaker_rewrap.py)).

## Guided runs and paid work

### Estimates and approval

Guided main text shares configuration while retaining independent database and event selections.
Each phase binds its estimate to source, scope, provider and pricing, guidance, and layout.
New estimate and Batch preparation workspaces are temporary until approval; they do not enter saved history or contribute translated outputs.
Each Translate click discards that phase’s unapproved preparation and creates a fresh estimate, unless the phase's latest finished estimate is still current ([freshness](../backend/dazedtl/engine/util/freshness.py)), or its inputs differ only in what a model switch prices differently: Translate then reopens it ([unchanged_estimate](../backend/dazedtl/translation/guided_actions.py)) and its dialog marks Estimate cost as reused, so declining or closing a review costs no second estimate.
A model switch only prices an estimate differently ([repricing](../backend/dazedtl/translation/repricing.py)) when the connection and request settings stay the same, a sample request built for each model carries the same messages ([request_text](../backend/dazedtl/compatibility/request_text.py)), and the provider counts tokens the same way for every model, which leaves out Claude.
Each estimate records the shape of its inputs without what such a switch changes, and its counts are then priced with the new model's rates by the engine's own formulas and DazedTL's pricing layers ([estimate_prices](../backend/dazedtl/compatibility/estimate_prices.py)), which a test holds to the engine's estimate for that model.
A review's model can be switched in its dialog: the reviewed preparation is discarded first, since settings wait for its worker to end, and a Batch then prepares its requests again for the new model while the dialog shows the estimate at its prices.
An estimate stays reusable through its Batch preparation and ends with approved work started from it or a Claude count it still needs.
Decline discards a Batch preparation after its worker exits and keeps the finished estimate; restart removes all temporary work, estimates included, so a newer release estimates afresh.
Approved work is retained before signaling the worker, including separately approved speaker translation.
Existing historical runs remain intact.
Paid review requires that matching estimate and rechecks it before the one-use submission.
Cost dialogs focus on price, selected scope and approval; an optional Preview request opens the existing prepared text, context and exact payload without preparing or submitting work.
Preview request shows requests an estimate kept: estimates keep them on connections that support Batch, while Live-only connections estimate from token counts and offer no preview; Batch review previews the collected requests it submits, numbered like its request count, without the Live names pass sent before it.
Every RPG Maker estimate parses all its files in one worker process, as Batch collection does; a process per file took seconds each on Windows.
Live RPG Maker translation reuses its worker processes the same way, one per concurrent file, each handed the next file when it finishes one; a file that fails ends its worker, and a fresh one takes the files after it.
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
Cost comparisons explain reuse of repeated instructions in plain words and include cache creation without promising savings.
A Batch whose provider caches prompts is priced as a range, from every request that shares a cached prefix reusing it to none doing so, because Batch cache hits are best effort; the approval shows both ends, and an Assistant-led quote's cost is the higher one.
Claude caches a request's tools and reply schema with its instructions, so each line count's schema is a separate cache entry, and an estimate counts and prices each one.
Claude requests cache their instructions for five minutes in both Live and Batch.
A Batch starts most of its requests together, so many write the cache instead of reading it: two of three real Claude Batches read it on about one request in ten, and a five-minute write costs 1.25 times input where a one-hour write costs twice.
Receipts price each write at the lifetime Anthropic reports for it, and results saved without that split count as one-hour, which every Batch used before.
Estimates count tokens with the GPT-4 encoder, except that Claude estimates in both methods use [Claude's own count](../backend/dazedtl/engine/util/claude_tokens.py), because Anthropic bills by a tokenizer that turns the same text into more tokens.
They send each cached prefix with its reply schema and an evenly spread sample of 24 whole requests to Anthropic's free token-count endpoint and scale the approximate count of the rest by the sample; if any count fails, the whole estimate keeps the approximate count.
A Translate estimate's worker has no credential or network, so a finished Claude estimate is counted again before its run completes: [estimate_pricing.py](../backend/dazedtl/compatibility/estimate_pricing.py) prices its kept requests in a separate process that opens the network only for that endpoint, with the run's own credential.
The count runs on the run's worker thread, so snapshots never wait on it, and stopping or discarding the estimate ends it.
Its process starts beside the estimate and waits for the key until the requests are ready, so its startup overlaps the estimate.
A Batch preparation counts the requests it submits itself, so the estimate leading into it, and every estimate in a launch with providers disabled, keeps the approximate count.
A speaker approval's run counts the name requests it would send the same way.
A cost review whose estimate kept the approximate Claude count says so.
The [Batch pricing adapter](../backend/dazedtl/compatibility/batch_pricing.py) calculates new GPT-6.1 Sol cached quotes from native token counts and frozen input/output rates using its [documented cache rates](https://developers.openai.com/api/docs/models/gpt-6.1-sol); saved historical estimates remain unchanged.
Inspection leaves Review cost available, while Translate always prepares the Batch or Live review again.
Approval rechecks the temporary preparation’s current inputs before the native one-use approval controls submission.
Once approved, the frozen request remains authoritative for recovery and is never silently rebuilt.
The fresh Batch speaker check validates unresolved nameplates against frozen files and the current glossary before collection; it retains its separate approval if translation is needed.
The estimate leading into a Batch scans the nameplates beside its own worker, and the preparation reuses that scan and submits the estimate's own requests when its frozen plan matches the estimate's ([adoptable_requests](../backend/dazedtl/engine/desktop/backend/manual.py)); it reads the files again only to collect after its names step translated names.
Nameplates may contain character names or other display labels, so the review does not assume a character identity.
A nameplate a registered reference game already translated one way, in at least 90% of its occurrences, takes that translation without a request.
Every name the step or a later run's reuse adds is marked `Unverified nameplate` in the glossary, because it was translated apart from its story: a cameo's 存子 became "Sonko" where its creator reads it Aruko; Project Setup lists the marked rows as guesses and removes the marker from each name it verifies.
This small preparation uses Live pricing to avoid waiting for a separate name Batch, and the review distinguishes it from the selected Batch mode for file text.
The file-text Batch receives its own cost review after names are resolved.
Collection itself never sends a Live request: a label or plugin argument translated on its own, such as a map event's `<LB:>` note, travels in the file-text Batch as a one-item request, and text collection cannot queue stops it before anything is sent.
The [name-result adapter](../backend/dazedtl/compatibility/speaker_results.py) retains the native save outcome and a verified glossary snapshot independently of the later Batch decision.
It verifies each name against that glossary: one that does not read back is shown as not saved and asked for again by the next run, and never discards the others.
The shared observer exposes pending, saved and unavailable outcomes; Batch review and the request inspector’s Technical tab show the result with bounded, read-only translation inspection.
Name feedback is a compact secondary note below the reviewed cost and file scope, or beneath the active preparation status, with its inspection action adjacent.
Approval alone never establishes success.
Declining or stopping the file Batch keeps approved names reusable in the next run’s frozen glossary, with current glossary entries and aliases taking precedence.
Paid names also join the game glossary: collecting a completed run copies its glossary over the game’s and refuses one changed since the run began, so the observer adds names the game glossary lacks only once the latest run is a Batch that can never complete: declined or stopped before its own approval, with no Batch sent ([publish_names](../backend/dazedtl/translation/guided_runs.py)).
It adds each run’s names once, to the Speakers section, while no run or operation is active and no glossary draft is open; a name the user later removes stays removed.
Reuse is bound to the project, target language and source pass, participates in estimate identity, and preserves the shared guidance and drafts.
Older runs, including those whose first receipt version called a finished save unavailable as a whole, can recover exact entries only from retained approved names, native save evidence and that run’s glossary.
Closing preparation after approving names preserves the paid run.
Read-only provider details resolve the submitted connection from canonical settings by its recorded runtime name, endpoint and organization, regardless of the active account.
Provider monitoring and new runs have independent isolated workers.
Cost approval checks its own frozen preparation and one-use token under the API lock; other runs cannot revoke it.
Existing Live resumes retain their frozen settings and require explicit review; Batch recovery follows saved provider receipts and the frozen clarification allowance described above.
New remaining work requires a fresh estimate and spending review.
The compact footer keeps Translate and available Apply actions beside the selected scope.
Translate immediately opens one stable estimate dialog; preparation, cost approval, no-work results and actionable failures stay inside it.
While it works, the dialog shows the [steps](../app/src/features/guided/estimateActivity.ts) to the cost review: Check files and Estimate cost, then for Batch Prepare Batch, which also holds any names review and name pass.
Each finished step shows how long it took, the current one its file count and remaining time, and the footer the time since Translate, so a large game's wait is visible from the start.
Each Batch phase starts its own file count, so a speaker scan the Batch has to repeat is never read as its requests' progress.
Files differ widely in how long they take, so [remaining time](../app/src/ui/workTime.ts) follows the last half minute's pace, appears only once that pace has been measured for long enough, and grows while one file takes longer than usual.
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

### Whole-game estimate

Context's Cost estimate prices every Translate task that sends game text through the API key: Database files, Maps & events and Other event text with its chosen sources.
It covers each task's whole file group, independent of the selection, so translating a small first scene leaves its scope unchanged.
[full_estimate.py](../backend/dazedtl/translation/full_estimate.py) starts it as a tool operation, never as a run, so it creates no preparation, approval or history run, and no paid work can follow from it.
The [worker](../backend/dazedtl/compatibility/full_estimate.py) builds each task's frozen plan with the engine helpers and request policy a Translate estimate uses and runs the same offline estimate worker, starting each file from its saved translation, working copy or game file as a run would, so its figures match each task's own estimate.
A Claude estimate is then counted again as a Translate estimate is (see [Estimates and approval](#estimates-and-approval)); a failed count keeps the approximate figures, which the task says.
The tasks run side by side, each with its own workers and count and with its inputs linked to the operation's one staged copy; the first task that fails stops the others.
The newest finished operation holds the saved estimate.
It reads current while every task's estimate inputs match: files, sources, guidance, options, layout, connection and prices ([freshness](../backend/dazedtl/engine/util/freshness.py)).
A model switch that only prices its requests differently (see [Estimates and approval](#estimates-and-approval)) keeps it current at the new model's prices, from the counts the result keeps beside each task.
Estimating again while it reads current would only repeat it, so the action waits for a change, except to retry a failed Claude count.
They are computed with the Live configuration, since one estimate prices both Batch and Live; switching between them only changes which total leads.
Stop ends the worker and keeps the previous estimate.
While it works, the worker reports each task's state and file count as the operation's structured activity, never parsed from its status line, so tasks can also run side by side; the panel shows them as steps with the same remaining time as the Translate dialog, and a saved estimate says how long it took, as a guide to the next.

### Frozen request policies

New API runs freeze a provider-default generation policy before estimation and review.
The compatibility adapter omits the native engine's implicit temperature, frequency penalty, and reasoning effort; current model preferences expose no explicit overrides for these parameters.
The policy participates in estimate identity and applies to both Live and Batch request construction.
Saved runs without this policy retain their original parameters and recovery behavior.
New API runs also freeze a [single clarification retry](../backend/dazedtl/translation/refusals.py) for provider refusals.
A refusal is the provider's refusal signal, a refusal message in place of the reply, or a note in place of a line or inside one, such as "[Not translated: …]", "[Omitted]" or "Translation declined."; one such line refuses the whole request.
Notes that real lines can also hold, such as "(Omitted)" for 中略 or a character who cannot translate an inscription, count only when that line's own source does not explain them.
The clarification identifies the existing fictional source and the owner's adult-character statement without changing source facts or asking the provider to disregard its rules.
Live retains both attempts and their usage; Batch submits only refused rows through the same Batch provider and retains successful originals.
The [retry journal](../backend/dazedtl/translation/batch_refusals.py) records intent before submission and saves returned job IDs before polling, including across restarts.
It keeps the original Batch's responses and the clarified payloads it sends; the original payloads stay with the run.
A clarification can wait for hours, so its polls read this small journal instead of downloading the original output again.
Cancelling an Assistant-led run then asks the provider once to cancel each submitted clarification, records that request in the journal and submits no waiting one; the run keeps the rows and usage they finished.
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
A Batch matches glossary context against its glossary freeze, never the live glossary that consume grows with names from earlier files, so a Batch that submitted its estimate's requests partitions them as the estimate did ([state_requests](../backend/dazedtl/compatibility/state_requests.py)).
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
A separate same-line speaker policy, `SAME_LINE_SPEAKERS`, sends a nameplate sharing its line with the text, such as `【Name】：text` or `Name「text`, only as the `[Speaker]:` prefix, so the model does not write it into the message a second time.
New MV/MZ runs also freeze a battle-message-users policy, the database parser's `BATTLE_MESSAGE_USERS`: a skill's battle messages carry a note naming the actors that learn the skill, through their starting class, an Add Skill trait or a Change Skill command, and the enemies whose actions use it, and those names bring their glossary entries, so the model can choose pronouns for the battler.
A skill granted any other way, such as by a plugin, has no users, and its battler stays gender neutral, as does a state message's, whose subject is whichever battler has the state.
Its second version also reads the party: when System's starting party and every actor a Change Party Member command or an `addActor` script adds come to one named actor, that actor uses every skill no enemy uses, other actors are left out of the notes, and a state's message1, which shows when a party member gains the state, names that actor; an `addActor` whose actor is not a number leaves the party unknown.
Runs frozen with the first version keep its requests.
New MV/MZ runs also freeze a page-packing policy, the event parser's `PAGE_PACKING`: in maps, common events and troops, a page of at most `SHARED_PAGE_ENTRIES` (10) message boxes and choices shares a request with the file's other short pages, each labelled with its event and page, because each request otherwise repeats the full system prompt.
A longer page keeps a request of its own, so no other scene's speakers or subjects bleed into a conversation, and its choice menus join that request in play order when the page fits one request; the parser's other lists keep their requests.
A packed reply of the wrong length writes none of its pages, which stay untranslated for a retry.
New MV/MZ runs also freeze a source-text policy, the parser's `SOURCE_TEXT`: text still to translate is what [source_text](../backend/dazedtl/engine/util/source_text.py) reads as Japanese, Japanese letters outside control codes and their arguments, the rule Guided's line counts use, so punctuation and brackets a translation or the game keeps, such as `【Saving beforehand is recommended】`, and a plugin code's argument such as `\SA[びっくり]` read finished.
Under it map display names and note labels, like other text, are sent only while they hold Japanese; runs frozen without it read Japanese by `LANGREGEX` and send map names and labels on every pass, keeping their requests.
On a 970-map game this cut a Maps & events estimate from 4,089 to 2,173 requests and from 23.5 to 14.0 million input tokens.
Assistant-led organize applies the same 10-line rule to API requests (`SHARED_LINES` in [organize.py](../backend/dazedtl/translation/organize.py)).
Estimates, Live and Batch use these policies; older frozen runs retain their original parser and request identities.

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
An ended provider receipt with a matching submission manifest and counts covering every request, a canceled or expired one included, remains submitted while awaiting download, as does a Batch the provider is still canceling; missing fetched responses or conflicting evidence retain submission uncertainty and outstanding work is never automatically resubmitted.
The [submission journal](../backend/dazedtl/compatibility/batch_continuation.py) records a create the provider refused outright with a client error, such as OpenRouter's HTTP 402, so its requests read as never sent and a new approval may send them; timeouts, conflicts, server errors and lost responses can follow a successful create and stay uncertain.
The worker also records a submission attempt that failed before journaling any create, such as one whose SDK client could not be built, so its requests read as never sent too; an approved run without either record, including older runs and a worker killed mid-attempt, stays uncertain.
A journaled create's requests stay uncertain until its receipt reaches the saved manifests, also beside earlier submitted chunks.
A failed Live request reads as never sent only when every HTTP try inside it failed to connect or was refused outright, as the [transport observer](../backend/dazedtl/compatibility/transmission.py) records, because SDK retries can hide a processed try behind a later refused connection; anything else stays uncertain.
Cancellation binds one provider Batch and its request mapping through a project-owned, one-use review; it retains the queue and receipts.
Terminal collection uses the recorded connection and retains successful responses.
It settles any authorized clarification Batch before native fetched-results consumption, including partial results from canceled Batches.
Unknown or conflicting responses retain their recovery guard.
Consumed Batch history plus a matching frozen plan and unchanged, complete output receipts settle finished requests without inventing per-request validation.
Missing outputs and native mismatches retain unresolved receipt states; identical text in different known files does not create an overlap.
The backend-owned [Batch monitor](../backend/dazedtl/translation/batch_monitor.py) checks interrupted runs automatically across registered projects, independently of the current screen and native worker pointer.
A worker that ends after every provider Batch ended, such as one that finds its Batch canceled, leaves the results to the monitor's next check, and its run reads as collecting rather than failed until then.
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
A request without a fetched result fails only its file, before any Live request, so later files still save theirs; the file's failure reason, written once by the [engine](../backend/dazedtl/engine/util/translation.py), tells a request the Batch sent but got nothing back for, as a canceled Batch leaves, from one the Batch never sent.
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
Older runs saved refusal notes as translations, and a run sends only lines still in the game's own words, so a Guided phase puts each such line's source back in its selected working copies before it lists them ([saved_refusals](../backend/dazedtl/translation/saved_refusals.py)).
The source is the line's `_original`, through QA's inventory mapping, or outside event commands the original game file's value at the same place, which covers names the engine keeps no `_original` for; a note without a known source stays.
The run records its inputs as restored, so its estimate stays current, and the file counts such lines as left until a run replaces them.
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
The Live names pass before a Batch is its own first group; its requests belong to no file, so they never count toward a file's lines, skipped-file evidence or continuation reuse.
A Batch translates every selected map's display name in requests made while it parses the first map; each line records its maps, so a line counts toward the maps it names, a name two maps share counts for both, and a rejected name marks only those maps.
Those requests and their Batch receipts stay the first map's, so consume and clarifications match them as before.
Runs frozen with the map-name-identities policy (`MAP_NAME_IDENTITIES` in [preferences.py](../backend/dazedtl/settings/preferences.py)) identify each line in every map it names, as a Live run identifies that map's name, and save its translation under each of those maps, so Live and Batch reuse each other's names whichever map a selection starts at.
They also reuse a name an older run saved under the first map; older runs keep the first map's identities, so their Batch consume rebuilds the requests it collected.
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
Each request records the identities of exactly the lines it sends, which the translator names while building it: a chunk leaves out lines without source text, so requests do not follow a call's lines one for one.
Continuation reuses these values locally across expanded or narrowed selections when the relevant source bindings and file versions match.
If compatible runs contain different validated wording for one identity, the newest run by creation time supplies the reusable value; historical alternatives stay unchanged and do not block preparation.
Existing working translations still go through the native skip-translated behavior.
Every selected file is still parsed; untranslated or changed text within a previously translated file remains eligible.
Reuse is per text identity, never a file-complete skip.
New provenance associates validated identities with their files so changing one source does not reuse its old values.
Verified completed files from partial runs are collected only when their frozen inputs still match the working copy; newer edits are retained.
When a call mixes reused translations with remaining source spans, runs frozen with the reuse-stretches policy (`REUSE_STRETCHES` in [preferences.py](../backend/dazedtl/settings/preferences.py)) send the spans together in requests up to the request size, each labelled with the lines before it and their earlier translations, so scattered leftovers do not each pay for a full prompt; older runs, and a call with one span, send each span with its preceding source.
A mismatch in one request preserves its lines' native fallback and continues the others.
The adapter retains successful translations, all attempted usage and the final mismatch flag without changing native validation or retry rules.
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
Database files and Maps & events read their files, as [File status and Lines](#file-status-and-lines) describes; Other event text still follows its runs' request receipts and verified output, independently of checkbox selection or the current attempt.
The file list uses the shared display states.
Untouched files show Not started, including files whose requests all failed without returning lines, with that reason in the detail.
A rerun reads the earlier run's output and reuses its results, so a verified pass with no new requests over a file an earlier run translated shows Ready to apply, or Applied once that output is in the game.
A file no current run has changed or sent requests for, per [translatedFiles](../app/src/features/guided/translationView.ts), still holds the game's own text: a pass that sends nothing for it found nothing to translate, so it shows Done during the run and after, with that reason in the detail.
Preparation, queueing, provider work, cancellation, collection and saving show Working; a pending cost approval shows Needs review without a spinner.
Needs review also covers partial, rejected or unsaved results and never establishes completion.
Ready to apply requires verified full output or explicit evidence that no requests were needed for a file an earlier run translated.
Applied means the game matches the saved output, or the latest Apply receipt holds it or an output a later run built from it, through [applied_versions](../backend/dazedtl/translation/guided.py).
Hand fixes, Line widths and QA fixes in the game therefore leave it Applied, as does a later phase's Apply; another Apply or a restore replaces the receipt, and Reload from game retires the file's runs.
An Apply that fitted an output to the Line widths records the bytes it wrote beside the output's hash, so the file reads as Applied and not edited, and the next Apply warns of no later edits.
Recorded output that is missing or changed shows Blocked, and a file changed in the game since its working copy was made shows Outdated.
Detailed states and request counts belong in Inspect and the approval dialog.
The latest run's failure, or a Batch that could not be confirmed as sent, shows on its task with the reason instead of a finished notice; collection errors and rejection details remain in the inspector and run views.
Dismissing that [banner](../app/src/features/guided/RunFailure.tsx) is a browser-profile preference for the run and a fingerprint of its reason; it hides no run, receipt or execution guard, and a different reason shows again.
The observed `workerStatus` retains the actual worker state separately from public monitoring activity.
File ownership, saved metrics and task completion use that worker state, so a background check cannot promote an older run or make its whole scope look queued.
Automatic Batch monitoring cannot mark every file as submitted or override saved progress: In progress for provider work requires the file's latest submitted requests to be mapped to an explicitly active provider Batch, using the shared provider-state rules.
Terminal, unknown, missing or unrelated Batch receipts cannot make retained submissions appear active.
Pending collection also requires matching ended-Batch and finished-request evidence.
These display rules never settle submissions or release execution guards.
A finished Batch collection can identify files with no new requests only when its recorded builder provenance covers the selected scope; deduplicated callers remain included, and absent legacy evidence stays unknown.
Provider-waiting rows and active Batch stages use the shared activity indicator, while cost approval and files with no requests stay still.
Selection locks during active work while search and inspection remain available.
Per-file cost and processing time come from native result receipts, retained beyond the log cap; Batch collection figures are excluded and consumption time excludes provider waiting.
A run's TOTAL adds up those receipts with their tokens, plus the receipt of any names pass before its files, which the file list leaves out.
Each attempt starts from the run's saved receipts, and a worker reused for several files reports each file's figures on its own.
The file list retains cost and time from the latest run that changed the file, comparing its recorded output hash with its frozen input hash; estimates, pending work and unchanged passes do not replace those metrics.
Missing receipts for a changed file stay unknown.
Line amounts follow the same receipts through [fileLines](../app/src/features/guided/translationView.ts): the lines a file's latest run saved, out of the lines that run prepared, counting each source request once at its latest attempt; a later "nothing to translate" check closes the file at what is done.
A latest run that finished a file with nothing to send found every line of the run that last translated it done, since it sends any line still in the game's own words, except lines holding a saved refusal note; those notes also keep a "nothing to translate" check from closing the file.
A Batch writes a file only while it saves its results, so its received lines count as saved once the file is written, and not at all when saving that file failed.
A Batch sends identical requests of several files, such as a scene two maps repeat, once; the queued request names each of those files, and its lines and validation outcome count in every one of them.
A Live run prepares requests as it works, so its files show only the lines saved so far until it ends, and Apply leaves them out until then.
Estimates carry no per-file lines, so a file without a run shows no amount; the Project page totals the known amounts with files applied and the recorded cost.
Saved-output counts there, on Apply and in the Check and Release notes about applied text leave out files no run translated, since their saved copy is the game's own text.
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
It lists one page of the selected group's requests, with Previous and Next for longer groups, and the inspector reads each page through `guided_requests` when it needs it.
Raw worker logs are not a separate content view: Technical ends with the retained log tail, which the compatibility readers still use as evidence.
Other-activity records open with their status, saved result and log in the same presentation.
Request selection and tabs persist locally without storing payloads in browser preferences.
The inspector has no separate provider-check control or transient remote status overlay; tab changes never contact the provider.
Saved translated output and applied files are separate counts.
Active per-file request states take precedence over retained checkpoints; a resumed worker takes ownership of its rows even when a newer completed attempt exists.
Live rows also retain the worker's current filename from `itemProgress` between requests, including after rejected replies.
The completed-file counter identifies the last finished file and cannot establish current activity; native command totals are not translation percentages.

### File status and Lines

Database files and Maps & events read each file's status and Lines from the file itself through [file_lines](../backend/dazedtl/translation/file_lines.py), independently of checkbox selection and of the runs that wrote it.
The backend reads the file's newest copy (its translated working copy, else its working copy, else the game's own file) once per change, by its digest.
A line is one message (a 101's name box with its 401 rows), scrolling text block, choice, choice help block while Comment text is on, map display name, event note label, database field or system term, without what another task or no task translates, such as System's currency unit and actor name changes.
What an event file holds of these is defined once, in [rpgmaker_scope](../backend/dazedtl/engine/util/rpgmaker_scope.py), which the engine translates from too; database fields and system terms are the ones Text QA's never-translated report lists.
A line is in scope when its source holds Japanese by the engine's own rule ([source_text](../backend/dazedtl/engine/util/source_text.py)): the `_original` the engine keeps, or for a translated map name or note label, which keep none, the original game file's.
It is translated when it holds no Japanese and no refusal note, since the engine sends a value while it holds Japanese whatever its `_original` says; a name box counts only the name the engine translates.
The engine probe ([engine_runtime](../tests/fixtures/engine_runtime.py)) runs a real pass over the fixtures and the `finished-text` game variant and checks that the engine sends only Japanese from the lines left, for exactly the files with lines left, leaves none, and sends nothing on a second pass.
Lines shows the lines translated of those in scope from the first look; a Live run still working on a file shows the lines it saved so far, and the file's count takes over once the run is done with it.
A run's work while it is in progress for the file shows Working, or Needs review while a cost approval waits; otherwise the file decides.
Nothing translated shows Not started, lines left show Needs review with how many and why (never translated, choice help that Comment text now translates, a refusal note), and Inspect opens on them; a submission that could not be confirmed names that instead.
A file with none left shows Ready to apply, or Applied once it is in the game or has no translated copy of its own, and one with nothing in scope shows Done; one the backend cannot read shows Blocked.
The task is done when no file in its group has lines left, no run works on one and none changed in the game, and the overview adds up the same counts.

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
Apply captures the actual overwritten bytes for rollback at execution, backing up every file before its first write so its receipt is saved once.
An Apply binds the saved outputs it publishes by hash instead of copying them for its review, unless it fitted one to the Line widths; other batches freeze copies of what they write.
A finished batch keeps only its backups, and the next review discards reviews older than their 20 minutes with the copies they froze.
An Apply review lists the files it overwrites without comparing their text, which took minutes on a large game; a restore's review shows the start of each file's [diff](../backend/dazedtl/compatibility/text.py), matched window by window after each change.
QA and restore keep their existing exact-before checks; no background synchronization is performed.

Translation, Apply, Assistant-led's game writes, Text QA and new Line widths fit text with one [fitter](../backend/dazedtl/engine/util/rpgmaker_rewrap.py), so text written by one never needs fitting by the next, and Check has no line width task.
It measures a line by what the game draws in its box: name-window and alignment codes take no room, names, icons and variables take a generous fixed room, since their values vary, and a full-width character, or a symbol the Japanese fonts RPG Maker games use draw full width such as ♥ or …, takes two, which captures of Fuuma Chronicle confirmed.
Letters of ambiguous width, such as é or Greek and Cyrillic, take one, as MV/MZ's M+ and VX Ace's VL Gothic draw them.
It wraps like the Japanese where the English allows, through [wrapShaped](../backend/dazedtl/engine/util/dazedwrap.py): blank first rows stay, lines break after the sentences the Japanese breaks after (and its clauses) and before list items, and otherwise lines are as few and as even as they can be; a message longer than its window starts each page after a sentence.
A message window pages instead of cutting rows off, so a message keeps each list item it had on a row of its own on rows of its own, an item too wide for its row wrapping alone.
Measured on six translated games against filling each line in turn, it matched the Japanese row count for 51-93% of messages (33-87%), broke after a sentence or clause at 42-77% of line breaks (9-14%), and left a short stray last line in 0-2% of multi-line messages (18-32%).
Apply fits each translated value wider than its box in the output before freezing it; Japanese left untranslated and text with no box, such as a text picture, are never rewrapped.
Kana and kanji mark text as Japanese; the middle dot and long vowel mark alone do not, since English uses them as bullets and dashes.
Database text keeps its authored lines, a list's items one a line, until they need more rows than a window of fixed height shows; then the text flows together, its items starting a line where they can, since the game cuts off a row past the window's last.
A note's prose tags are decided one by one, so an English body fits beside a tag left in Japanese.
A text variable (code 122) is fitted only where translation wrote it, so a script of the game's own stays exact, and its text wraps around `${...}` and `#{...}`, which a line break would turn into a syntax error.
Translation [writes](../backend/dazedtl/engine/util/rpgmaker_script_strings.py) a text variable's operand as a script string, so a backtick or a `${` the translation adds is text, while an interpolation its source runs, such as `${$gameActors.actor(1).name()}` for the hero's name, keeps running wherever the translation keeps it.
In that string `\n` breaks a line except where it starts a name code: `\n[1]` or a name window such as `\n<Alice>` or `\nc<Alice>`, so its wrap never breaks a line right before a word that starts with `[` or `<`.
A message whose rows are stored in several Show Text commands, as Assistant-led writes one Japanese line per command, is fitted as one text and its rows go back over the same commands, a row each with the rest in the last and empty commands when it has fewer (`spread`); no command is added or removed, so a saved game's place in an event and Len's next write still line up.
Fitting each command on its own would have pushed 353 of Fuuma Chronicle's 3,307 overflowing messages past its four-row window, against 23 fitted as one text.
Within a message, commands left in Japanese and labels such as 【Name】 keep their rows, and a row that changes the code repeated on each row, such as centring, or the font size starts its own text; Scroll Text rows are the author's, often a list such as credits, so a row too wide wraps inside its own command.
Assistant-led's `write_rpgmaker` and `rebase_rpgmaker` fit the staged text to the game's saved Line widths, or the defaults Text QA also reads, and list text a fixed window still cuts off for the assistant to shorten; its assistant confirms the widths it measures with `playtest --layout` and saves them with `line_widths`, where Guided keeps them.
Saving widths also fits the text the writer already wrote, in the data files holding its `_original` sources, so text written before the widths changed fits the new ones.
Until a game has widths, it takes its engine's stock windows' from [game_settings](../backend/dazedtl/engine/util/game_settings.py): VX Ace's 544-pixel windows hold 52 characters, 40 beside a face, as captures of the engine's own windows confirmed, against MV/MZ's 60, so its assistant confirms measured widths by running the game itself, which `playtest --layout` cannot, and an Ace project still on the MV/MZ widths earlier versions gave it takes Ace's when opened, with its applied text fitted to them.
New Line widths, saved by hand or measured, queue a `fit_text` publication of the areas whose width changed, which [starts](../backend/dazedtl/translation/text_fit.py) once nothing else runs and reports beside Save line widths; it rewraps only lines that no longer fit, so hand layout that fits stays.
Like any write to the game, it waits while the game folder has an unfinished Git operation, such as a game update's merge whose conflicts its files still hold, or is off the translation branch; the request stays queued and starts once Git is done.
It fits only the files DazedTL applied, leaving files translated another way as they are, and a file still as the last Apply wrote it records the fitted bytes as that Apply's, so the next Apply reads no edits; History restores it like QA's batches.
Character counts only choose what to look at: text a fixed window cuts off even fitted goes to Text QA as a `text-fit` check, and QA's captures and the playtest confirm what the game shows.
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
The app-owned clean packager uses one inventory for inspection and writing, retains player documentation, excludes known private and translator material and names Windows can't extract, and verifies the source and destination before atomically replacing a ZIP.
Of the other files it ships only those a saved game snapshot holds (the original, the prepared game, an update or a game backup) or the translation's runtime scope names, so a translator's notes, downloads and browser caches stay out; when either list can't be read, it ships them all.
Guided patches add current applied-image receipts and explicitly reviewed image/font paths to the runtime scope.
Each game's GameUpdate config, `gameupdate/patch-config.txt`, belongs to the engine's [gameupdate_config](../backend/dazedtl/engine/util/gameupdate_config.py).
It writes the compact file from Settings' GameUpdate defaults and the game's repository, which the game's `.dazedtl/settings.json` keeps with any values the game sets itself and the digest of the file it last wrote.
The [action guard](../backend/dazedtl/engine/desktop/backend/workflow_actions.py) that binds saved runs, QA and reviews to the game's settings leaves that record out, so writing it never marks saved work Outdated.
The repository comes from the `origin` remote when that names the configured owner; a placeholder is never written, and a working config it has not seen is adopted as the game's own.
A file changed after that write keeps its values until the user keeps or replaces them on the Project page.
Settings offer GameUpdate's own forge names, gitlab, forgejo and github; a saved gitea reads as forgejo.
[GameUpdate](../backend/dazedtl/translation/game_update.py) reconciles the file when a game is opened or selected, when the window regains focus, after Settings change and before a scope review or release, never while an operation holds the game; observations only read its status, cached on Git's metadata and the files it reads.
Every translation version commits a complete config with the patch scope, as a translation-only addition when the original lacks it, so the Len `.gitignore` block allows it; a placeholder never enters Git.
Guided releases wait while GameUpdate has an owner but no repository; a game without an owner, or with an edited file, still builds.
The status warns when no Git remote shares the config's site and `owner/repo`; hosts of one forge, such as `ssh.gitgud.io` and `gitgud.io`, share a site.
Local patches omit the config unless their commit is the verified public version, which Guided's patch never claims; clean ZIPs include it only with the frozen engine's verified public commit stamp.
Player updater scripts remain included but cannot update an unstamped local build without configuration.
Archive availability describes the saved ZIP on disk, never freshness against later game edits.
Archive names and additional asset choices are retained per project, with separate game and patch names.
A clean game ZIP holds the game in a folder of the archive's name rather than the source folder's, so players get the name the translator chose.
RGSS3's Game.exe reaches its library through the ANSI code page and fails as "RGSS301.dll File corrupted" from a Japanese-named folder on English Windows, and Explorer's Extract All adds a folder of the archive's name, so a VX Ace game ZIP's name must be ASCII.
Neither operation manufactures a user-review record or completes Len's report-based QA.
The project helper cannot invoke Guided packaging; its separate QA requirements remain in force.
Legacy Guided review receipts remain readable for existing records.

## Plugins and images

Guided Plugin files and Images are Translate tasks; positions saved by earlier stage layouts open them without rewriting saved run records.
The [plugin service](../backend/dazedtl/plugins/service.py) owns retained investigation, working copies and checked publication for MV/MZ root and `www` layouts, and for VX Ace's Ruby scripts in `ace_json/scripts`.
The assistant decides which plugin text players see, and the user reviews neither files nor strings.
Apply to game writes every checked file in one click, because a list of files could not show what changed; it checks each file again and backs it up first, and Recovery restores an application after a review of its own.
An Acorn AST inventory and recursive decoded parameter paths bind reports to exact source bytes without evaluating plugin code.
Original Japanese database fields, notetags, command arguments and parameter evidence come from a verified source backup even after runtime JSON has been translated, so a task cannot start without it.
Known lookup values, code keys, embedded expressions, serialization structure and control tokens remain protected by the app and are never asked about; a file with nothing else, and no JSON it loads, needs no investigation.
A translated line may keep only a leading Japanese tag that unchanged code in its file matches with `startsWith` or `indexOf`, such as a script parser's `ア:` speaker tag; any other Japanese left in a target fails the check.
VX Ace has no plugins: its menus, battle messages and other interface text are string literals in the Ruby scripts Set up extracts, and the task covers those.
The [Ruby reader](../backend/dazedtl/plugins/ruby.py) gives them the inventory Acorn gives JavaScript, in Python so no Ruby ships: exact byte spans and the text Ruby makes of each literal, deciding from the code before it, as Ruby's lexer does, whether `/`, `%`, `?` and `<<` start a literal.
It skips comments, regular expressions and plain symbols, protects hash keys, index lookups, compared values and `when` clauses, and treats a translation that adds a literal, such as an unescaped quote or a new `#{`, as changed code.
A VX Ace game's originals are its database names, note tags and the strings its event scripts compare, read through the compatibility boundary from the preserved archive's or Data files' Marshal data; applying packs the scripts into `Data/Scripts.rvdata2`, as every write to `ace_json` does (see [Ace packing](#translation-execution-and-the-agent-boundary)), and labels too long for the screen come only from MV/MZ captures.
Dynamic configuration, malformed data and unreadable sources remain explicit blockers.
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
Then it hands out the labels the latest Text QA capture, of any focus, found squeezed or cut off that QA holds no line of, with each label's screen, capture and how short of room it is, because QA never writes plugin files.
A label's candidates are the text in the bytes each file gets, its working copy until it is applied and the game's file after, edits since included, that a loaded plugin can draw, whole or as an item of a short list, and that is no lookup value, code key or default; a label with none stays with QA as found in no plugin file.
The assistant shortens it in a copy of its own, so the translation's working copy keeps its checks; an accepted copy is checked against the bytes it started from, then as the whole working copy against the frozen original, with the shortened text as approved text that later translation of the file keeps.
The assistant confirms a shorter label on screen with the label check: the app plays the game in the [game window](../backend/dazedtl/engine/util/rpgmaker_window/launcher.cjs) with the request's shortening copies, frozen as they are, served in place of the game's files, capturing only the labels' screens, and [measures](../backend/dazedtl/engine/util/rpgmaker_screens/__init__.py) each label there as the text its changed candidates now draw in its place, which fits only when drawn in full while the old text is not drawn; it keeps its own last three reports beside the playtest's.
A label counts as shortened only when the latest check of exactly the reported copies shows it fitting, or could not run the game, which its decision records; otherwise the copy goes back with that as its failed check.
A label counts as shortened for the capture that found it, and a newer capture that still shows it, a capture QA takes again included, hands it out again; one the assistant keeps stays kept with its reason.
Once nothing is left, a copy asks the assistant to recheck every decision with its earlier findings, for text the user found untranslated in the game.
Apply and restore reviews omit hashes, working-copy and backup paths; execution rechecks the exact reviewed files.

The [image service](../backend/dazedtl/images/service.py) owns a project-scoped SQLite inventory, retained selection, discovery and editing contracts, saved reports, and runtime application receipts shared by Guided and Image Manager.
Indexing runs incrementally with cancellation; the renderer reads metadata in bounded windows and thumbnails through a [queue](../app/src/features/images/thumbnails.ts) with a cache bounded by size.
Windows and thumbnails on screen load first, and the rest of the view follows, nearest first, so scrolling finds its images ready.
Thumbnails are WebP at the screen's pixel density.
Previews decode each image once and hold the service lock only for the inventory lookup; the [server](../backend/dazedtl/api/server.py) answers them on a few workers outside the engine context, which redirects stdout process-wide, while every other request still runs in turn.
The observation revision leaves out the user's choices, so saving the selection or scroll position reloads no window; the selected images the filters hide are counted on their own, and a reload keeps each window on screen until it is replaced.
A save sends only what changed, and only an unsaved list holds the footer's actions, since their counts come from the saved list; the scroll position, filters, thumbnail size and previewed image save quietly behind them.
The selection is the list to translate, and the manager walks it through four steps derived in [imageFlow](../app/src/features/images/imageFlow.ts): the assistant investigates, the user chooses, the assistant translates, the user applies.
A click only previews, so looking never changes the list; the tick box, Ctrl/Cmd and Space toggle an image and Shift only adds, with [selectItem](../app/src/ui/selection.ts), and a Shift range that reaches past the loaded windows reads the images between in bounded runs.
The [viewer](../app/src/features/images/ImageViewer.tsx) fills a full-height column beside the task, toolbar and grid, because the preview is limited by height more than width; it reads the last clicked image at full size, unscaled when it fits the backend's largest preview, while its tile's thumbnail stands in; the saved view remembers which image it shows, as it does Compare's.
Discovery reports bind project, inventory revision, exact scope and source hashes, with per-image examination evidence.
Unexamined, failed, unreadable and changed sources remain unresolved; detector misses alone cannot certify no text.
Sound effects lettered into scene art are flavor, often hundreds per game: an image with nothing else is found Sound effects only and stays out of the list like a text-free one, and the image skill leaves them as they are in an image translated for its other text.
Manual choices survive recommendations and filtering, and only byte-identical sources can reuse discovery evidence.
An investigation report ticks each image it newly recommends once and opens the grid on the list, so an image the user took out stays out when the same request saves again; a report whose every image has a result completes the request even without its flag.
Until a report sets that flag, an image it holds as not examined is still to come, because the assistant saves its partial reports with those placeholders; the copied task keeps waiting instead of reading finished and calling the user back.
The translation task covers the list's images not yet in the game and makes their editable copies first, leaving out images that cannot be edited.
Applied images stay ticked, so a finished list still reads done and Edit text still reaches them, but the list's Recommended view and Unsure leave them to Applied.
Apply to game applies the list's translated images; a list that a click replaced in earlier versions gets its copied translation task's images back once.
Editing reports bind original and candidate hashes and a review version; changing either invalidates review.
Every image an assistant changes needs a [recipe](../backend/dazedtl/images/recipes.py) in the game's resource manifest: the command and hashed inputs that render it again and the regions its edit may change, so a later sibling starts from that recipe instead of pixels.
Reading a report checks each changed image's recipe against its exact candidate and runs the same [validation](../backend/dazedtl/images/validation.py) as the validator command the task hands the assistant, bound to the source and candidate hashes and kept while its inputs are unchanged.
A missing or stale recipe or a failed check holds the assistant's review, so the image reads Needs review with the reason, Apply never takes it and Assistant-led cannot apply it; the user's own review still counts, because only the user can accept an image the assistant cannot prove, and a copied task lists what to fix.
Requests from before recipes keep their accepted reviews, and copying a task again hands out a new request under the current contract.
The app never runs a recipe's command; the assistant's validator run does, so code in the game folder runs only in the assistant's own process.
Compare shows the discovery finding, current AI-review evidence and what holds a review; hashes and backup paths stay out of reviews because Apply rechecks the exact reviewed bytes.
Apply freezes the included batch and blocked reasons in a one-use preview, preflights every included asset before publication, and attempts runtime and metadata rollback on publication failure.
Publication freezes candidate bytes and journals the reviewed source, output and original-backup hashes before writing runtime files.
Restart reconciles only those exact authorized bytes, records partial or conflicting publication honestly, and retains reviewed restore for recovered outputs.
Preserved originals and durable receipts support reviewed restore without removing editable copies or editor work.
Indexing also records each image's untranslated original, its frozen copy, the Qt publisher's backup or the runtime file, with a tile signature kept in its own table.
The signature samples a grid from the decode the scan already makes, and is computed again only when that file changes.
[Families](../backend/dazedtl/images/families.py) groups same-size images that share most non-flat tiles, such as name cards or area banners that differ only in their lettering, with the region where they differ and how far each member is translated.
It checks only pairs that share one of each image's smallest tile keys, never every pair, and a complete scan groups again only after a signature changed.
The [background solver](../backend/dazedtl/images/background.py) rebuilds a member's text-free backdrop from its family instead of inpainting it, never changing pixels the whole family agrees on: consensus from members the lettering does not reach, then a fitted glow inversion or a Laplace fill, whichever wins a leave-one-out test on the consensus pixels.
Agents run it through [image_family.py](../backend/dazedtl/engine/scripts/image_family.py), which also checks a saved background for ghosts of a member's lettering.
A complete scan regroups the families, and each request asset carries its family, so the editing task rebuilds a member's background before any inpainting and fits an accepted sibling's text recipe with [image_recipe.py](../backend/dazedtl/engine/scripts/image_recipe.py) instead of measuring lettering by hand.
The solver uses the image tools' exact harmonic fill through the compatibility boundary, the same fill as the inpainting bridge and the image text editor.
Recipe commands name DazedTL's tools by placeholder (`{python}`, `{recipe_cli}`, `{family_cli}`, `{inpaint_cli}`), so a recipe survives an update or a move of the app.
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
Its background repair runs only the deterministic local reconstructions (the harmonic fill by default, or Telea or Navier-Stokes), never an installed model.
A render replaces only the source PNG's pixels and keeps its header and ancillary chunks, so gamma, colour profiles and text reach the game unchanged.
Its text styles share the effect model of fitted [text recipes](../backend/dazedtl/engine/util/imagetools/effects.py), so a recipe's slot style is a valid editor style and the panel edits every effect in it.
Its font list puts the faces a game ships in `fonts` or `www/fonts` ahead of installed ones, because recipes draw with them; a style saves only the list's id, which for a game font comes from its path inside the game, so a moved copy keeps it and no file path reaches the renderer from a style.
Native Image Text translation uses the preserved isolated manual runner with project-owned frozen inputs, a current estimate and one-use paid approval, independently of JSON translation runs and image application.
These runs have no run inspector, so a failed run's log tail appears beside its status.
Import revalidates the exported source scope and copies targets only; rendering still requires structural validation and image review before runtime application.

## UI and state decisions

### UX principles

Strive for [Nielsen's ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) when designing and reviewing this tool.
Make current state and the next useful action visible; use translation tasks and familiar language; offer clear exits and recovery; keep shared controls consistent; prevent scope and spending mistakes; make prerequisites visible instead of requiring memory; support both guided and experienced use; prioritize relevant actions; give errors a practical recovery path; and put concise help beside the task that needs it.
Use these principles to evaluate real workflows, rather than adding extra panels or confirmation steps to satisfy a checklist.
Give each idea one name and keep it everywhere: Apply only means writing into the game (settings are saved or used); Backups are copies you can restore and Versions are the Git history used to merge game updates; Line widths are the per-line character limits DazedTL wraps translated text to, with the rows a message window shows.
Assistant-led is the UI name of the method built on Len's game-translation skills, and code and records keep the `len` identifier.
Its starting prompt runs the whole method without the user: it asks only for spending approval, a missing API connection, denied access or a decision no source evidence settles, and a check it cannot make, such as a screenshot, stays pending instead of stopping the run.
Progress counts the assistant's first helper call as the run starting, because an assistant can work through a whole phase before its first report.
Its phase strip marks one current phase, the one the assistant reports working in, and shows half filled an earlier phase it left unfinished, such as translation while an API run works and it moves on to images.
Images is a phase of its own, as in Guided, so translation completes with the text.
Start over restores the original game in place and moves the attempt, its Git history, the playtest's fixes and anything the original lacks to `.dazedtl/archived` instead of deleting them, after saving game and project backups; save games, options and Image Manager work stay, and only the user can start it, so the project helper has no route to it.
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
Green, amber and red mark status, except that a text change shows its added side in green and its removed side in red; surfaces, lines and text each have a few named steps, and a new screen picks from them instead of adding a color.
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
The Project page's Status, History, Versions and Backups tabs serve both methods.
Status shows where a Guided project stands from the observed snapshot through [guidedProgress](../app/src/features/guided/progress.ts): the next unfinished required task, every stage's tasks with their completion and the last activity.
For other methods the Status card is the latest operation itself, shown through the shared [JobStatus](../app/src/ui/JobStatus.tsx), so no separate activity line repeats it.
Its one Continue opens the next required task, and the saved workspace position appears beside it as a smaller Last opened link unless it is a finished task before the next one; with every required task done, Continue resumes that position.
A one-task stage shows no done count, and an optional task not yet done says Optional instead of showing an empty mark.
Plugin files and Images say Needs review instead, on the Project page and their tabs, while work another project saved waits for the user's choice.
Plugin files completes from the same snapshot once every plugin's player text is translated, every plugin label Text QA found too long for the screen is shortened or kept, nothing waits to apply and every unreadable file is kept unchanged, Images once the translated images in its list are applied, or an investigation leaves nothing ticked, and Build release ZIP while a saved ZIP still matches the game; optional tasks never block the next required task.
Translate's Run history opens that stage's runs and estimates in a sheet over the task, with Inspect stacked on top, so closing returns to the task; Project › History lists every run.
An Assistant-led run's Inspect run opens a sheet over History, so it shows wherever the run sits on the page, with the run's requests one at a time and, for a Batch run, a Batches tab holding the provider job IDs, where an unconfirmed submission is attached to its job; the run's row only counts its Batches by state, and a failure of the row's own buttons shows after the last of them.
Its request chooser finds a request by number, line ID, state or failure message from `translation_requests`, which reads only the run's record, and each request error or source-review request on the run's row opens the sheet at that request.
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
Settings, the Project page and [Assistant-led](../app/src/features/translation/Translation.tsx) share the editor page model: a header, tabs, a scrolling body and a footer per tab; Assistant-led's Progress tab leads with the assistant's status and its Options tab holds the choices made before starting, its footers end with its starting-prompt copy, its context documents use the same DocumentEditor tabs as Guided guidance, and its Images tab hosts the same Image Manager as Guided, whose steps the project's assistant runs itself through the helper.
Its API run panel holds the assistant's estimate, and its button is the only approval: the project helper resumes only runs the user approved there, and each new estimate replaces the one waiting ([newest_estimate](../backend/dazedtl/translation/jobs.py)), so an approval sends one estimate's requests, and Progress and History show an unapproved estimate only while it can be approved.
While an estimate waits, its button is the page's one primary and the footer copy steps down.
The approval reaches the assistant only when it next uses DazedTL, so the panel reminds the user to tell it until then, and the prompt stays copyable while an API run works: it is built on the inputs already prepared, which the run's frozen requests depend on.
Every stylesheet loads through [index.css](../app/src/styles/index.css) in a cascade layer: tokens, base, shared UI, the app shell layout, then features.
A feature's rules override shared primitives regardless of selector specificity, so add a new stylesheet there and keep selectors simple instead of raising specificity to win.
Layouts must remain readable and usable across displays ranging from small laptop monitors to large 4K monitors or TVs.
Size and reflow content using the available window space and system display scaling; keep actions accessible on smaller displays and use larger displays without excessive stretching or gaps.
The desktop window fits its display's work area in logical pixels.
Every page centers one content column, `--content-width` in [tokens.css](../app/src/styles/tokens.css).
A workspace whose grid and preview use every pixel, the Images task in Guided and Assistant-led, is a wide [PageLayout](../app/src/ui/PageLayout.tsx) instead: it spans the window inside the gutter, and its frame rows and the app's messages above it widen with it so their edges keep lining up.
Frame rows (page headers, stage strip, task tabs, a page's or the app's [messages](../app/src/ui/PageLayout.tsx), scrolling bodies and footers) span the window and pad their content to that column; rows that do not scroll reserve the body's scrollbar gutter, so every edge matches across screens and window sizes.
Windows 720px tall or shorter compact the top bar and footers; fill editors and file lists keep a minimum height, and the body scrolls instead of collapsing them.
One choice among a few, such as Batch or Live and the file-group filters, uses [SegmentedControl](../app/src/ui/SegmentedControl.tsx), so it reads as one choice rather than separate actions.
Editable suggestion fields use the shared [ComboBox](../app/src/ui/ComboBox.tsx): its top-layer list scrolls within the available window height and opens above the field when space below is limited.
Action lists that open from a button, such as the project switcher, the [model menu](../app/src/features/settings/ModelMenu.tsx) and Image Manager's Select and More, use the shared [Menu](../app/src/ui/Menu.tsx) in the same top-layer style, with arrow-key movement and light dismiss.
An item that removes its own row, such as the switcher's Remove button for a game that is not open, keeps the list open, and focus moves to the item that takes its place.
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
Saved positions use the stage ids `setup`, `context`, `translate`, `check` and `release`; the backend's [retained_position](../backend/dazedtl/translation/guided.py) and the [navigation preferences](../app/src/app/navigation.ts) map the seven-stage ids and retired tasks to the task that holds their work, and Apply & Fitting's last view and the retired Line width check open Text QA.
Required and optional tasks are marked in workflow.ts; optional work never holds up the next step.
The app sidebar stays global; every phase uses the same one-row stage strip, which compacts when narrow.
The Translation screen has no header row; the top bar holds only the project switcher and app status.
One task occupies the editing body and its action footer stays outside the scroll region.
One copied setup task identifies speaker formats, runs local name collection, then uses those results for the glossary/context investigation, which also covers running jokes and recurring terms.
Guidance review and layout settings follow before the named database and dialogue actions.
Phase navigation restores the last available task saved for that project, falling back to the phase's first task when an engine-specific or removed task is unavailable.
Every phase with multiple tasks uses the same clickable task tabs, with completion marked after each label and optional tasks marked until done; views inside one task (Event text sources' investigation and source choices, Other event text's translation and comparisons) use secondary tabs below them.
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
Context uses compact Names & glossary, Event text sources, Guidance, Line widths and Cost estimate tasks.
Names & glossary shows one row per saved artifact with a consistent Saved label, plus the actual state of a running or failed local scan.
The shared observer updates saved results and guidance without a separate refresh action, and so do Other event text findings and Text QA findings; Image Manager keeps explicit refreshes because importing a saved image report validates it first.
Reference game folders are retained per project by [reference_folders.py](../backend/dazedtl/translation/reference_folders.py) and included as read-only source material in the copied investigation prompt.
Adding a folder only registers its path; it does not parse, convert or index the game.
Missing references remain listed so they can be removed or replaced.
Earlier native reference imports and their translation matching remain intact.
Context's Event text sources holds the investigation and source choice views, so its sources are settled before the [whole-game estimate](#whole-game-estimate) prices them; Translate's Other event text keeps translation and comparisons, and views saved by earlier versions open the task that holds them now.
Event text sources is complete once current findings are saved or a source is chosen by hand.
Its [investigation contract](../backend/dazedtl/translation/event_text.py) binds findings to selected event files, original data and plugin dependencies, and the installed parser's registry and built-in handlers, not the rest of the engine module, which most releases change.
The assistant applies a current report through the project helper's `event-text --apply`, and Use recommendations does the same in Source choices; either saves the recommendations and the consumed report ID in one write, and running work or a pending option draft refuses it, as for speaker findings.
Mixed or uncertain recommendations stay off; source choices need no separate review, and each frozen run records its source settings and report.
Code 122 requires explicit starting IDs, registered 357 and 355/655 selectors use exact installed identifiers, and 356 remains a single coarse switch.
Because plugins split 356 commands and many 108 comments on spaces, the engine joins a translation's words with underscores unless the findings name a built-in handler that keeps plain spaces or uses U+00A0, which MV's `split(" ")` keeps whole and the game draws as a space; the assistant picks each from how the handler's plugin parses and draws the text.
The same findings list exact 356 commands and 108 comments holding internal values, such as placeholders, which the engine leaves untranslated; applying them checks that each one is in the selected files' original text, so an internal value no longer holds its whole source off.
When players see 355/655, 356, 108 or 357 text that no registered entry or built-in handler captures, the findings add the game's own [custom patterns](../backend/dazedtl/engine/util/custom_patterns.py) instead of an engine change: a regular expression whose last group is translated, or an MZ plugin command with its plain-text arguments.
They are engine options of that project, so runs and Batch profiles keep them, and each takes its command before the installed handlers.
Applying refuses a pattern that captures no Japanese in the selected files' original text, two patterns sharing a command, a script capture holding its own quotes, a structured plugin argument and nested repeats, which can stall the engine on a line.
The compact selectors retain searchable, grouped drafts separately from saved engine settings and preserve hidden selections.
The comparison cache is literal-based and requires a matching coverage review; missing, malformed and nonmatching caches expose distinct continuation or recovery states.
New guided projects select all supported files, clear inherited advanced targets and start in Batch only when the active connection supports it; existing projects and frozen runs retain their choices.
Applying and testing a small scope is available before expanding translation.
Speaker findings use the structured contract generated by [speaker_setup.py](../backend/dazedtl/translation/speaker_setup.py).
A copied setup task binds its report to this project and request.
The app verifies source hashes before enabling only confirmed, high-confidence rules; prose reports and partial, stale or foreign findings cannot configure options.
The agent's scoped `speakers --scan` helper applies the rules and launches the preserved parser's scan phase in an isolated worker without credentials or network access.
It never translates names; literal nameplates and the native actor/variable lookup tables feed the rest of the setup investigation.
Once a scan applies the findings they stay a record of the inspected source, so a later edit to the game needs only a new scan; a saved scan that is no longer current names why, such as the game files that changed since it ran, because a setup task that could not see the reason rewrote valid findings after each unrelated commit.
The scan also runs text QA's [header check](../backend/dazedtl/engine/util/rpgmaker_header_check.py), described with QA below, on its copied files.
The setup task checks each flag in its scene and writes a [review](../backend/dazedtl/translation/header_review.py), which `speakers --fix-headers` checks against the current scan and the game's files before writing only the fixed headers' face and nameplate; it records every decision in the game's `.dazedtl/guided/header-fixes.json`, and the Speaker names sheet lists each flag with what the assistant fixed or kept and why, so the user reviews nothing.
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
An entry's translation is its first balanced parenthesized group ([split_glossary_row](../backend/dazedtl/engine/util/vocab.py)), so a translation may hold its own parentheses.
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
A version baseline that stopped before registering its branch is made again from the current files in the same repository, keeping the earlier attempt in the reflog; [unfinished_bootstrap](../backend/dazedtl/engine/util/version_update/git_workflow.py) recognizes it only while the repository holds nothing but DazedTL's own baseline commits, so any other ref, remote or staged change keeps the refusal.
The original-backup record lives in the profile's per-project lifecycle, while snapshots stay portable in the game's own store, so a moved or copied game opens without a record although its store holds the original.
Translation state then offers the earliest game snapshot there, which setup saves first, and the backup step takes it over (`use_source_backup`, bound to the snapshot it showed and refused once a record exists) instead of saving the current, possibly translated, files; saving the current files instead keeps its review.
The preparation worker records each completed stage against the current prepared files, stops on failure or cancellation, and resumes remaining stages without repeating current completed work.
Individual preparation tools update the same receipts; GameUpdate file installation does not imply a tested delivery configuration.
The receipts leave out `gameupdate/patch-config.txt`, which follows Settings and the game's repository after preparation.
New baselines require current preparation evidence at preview and execution; existing Git baselines remain usable without historical preparation receipts.
A finished setup continues to speaker/context setup only after the saved operation and baseline are confirmed, without starting an assistant task.
Recovery and official-version updates are project utilities, outside the normal preparation sequence.
They are the Project page's Versions and Backups tabs, whose primary actions use the shared [ActionSlot](../app/src/ui/ActionSlot.tsx) to stay in the tab's footer while content scrolls.
Versions shows an update's steps with what each finished step did, and the versions the original branch recorded ([version_history](../backend/dazedtl/engine/util/version_update/git_workflow.py)), read when the tab opens and again once the branch moves; each update commit records whether it came from a patch or a complete release.
The game's GameUpdate repository and its config's status belong to publishing, so they sit in the Guided Release task and on Assistant-led's Options.
A finished update hands Guided its own tasks: the applied comparison's files map to Database files, Maps & events, Plugin files and Images, and the data tasks open through a `select` intent that selects the changed files and keeps the other group's selection; Assistant-led reads its post-update task in one call and copies it.
The update view shows one current preparation/comparison at a time; a later attempt or changed Git state prevents an old comparison from being offered for application.
Guided keeps update steps in History's other activity, so the view lists no second history and its comparison omits the saved result; a failed step without its own control appears beside the interrupted-update recovery.
Backup history is grouped by game versus project files and appears only after the user chooses recovery.
Navigation never completes a task.
Prepared originals are summarized; recent activity holds saved history, while active work and required approval remain visible across areas.
Assistant task controls describe the expected return and report only copied instructions or saved findings, never an external process inferred from a click.
Every task that hands work to an assistant (Names & glossary and line width measurement, Event text sources, Plugin files, Images, Text QA and Assistant-led) shows the shared [AssistantTask](../app/src/ui/AssistantTask.tsx) panel: where the task stands, in the shared display states, what comes back, and a row per expected result.
It is a [StatusPanel](../app/src/ui/StatusPanel.tsx), the panel any work that is not the user's own uses to show its name, state and next step, such as Assistant-led's API run.
The panel reads Needs review only while a result waits for the user's decision in that panel; a result that saved itself reads Done, or Applied once in the game, and one waiting only to go into the game reads Ready to apply.
Findings that inform a later step read Done once saved, and that step holds any choices they leave, as Event text sources' Source choices do.
Outdated marks a saved result whose basis changed before it went into the game; edits after a task's result is applied are expected and leave it as it was.
Event text findings applied as source choices therefore stay current, through DazedTL updates too, until the selection reaches event files they did not cover, a plugin file with nothing left to apply keeps its state until a copied task rescans every file, and Text QA reads Applied once its own task's corrections are applied.
The task's main copy action stays in its footer; an optional companion task, such as layout measurement, keeps its own on its result row.
Each copy reply names its handoff: the task's kind, request id and the result files it expects back.
A task whose assistant keeps working after its first results also names the file it saves last, and reads Waiting until that file is saved after the copy; Names & glossary ends with its measured line widths, which its prompt saves last even when nothing could be measured.
A task whose assistant validates its results after saving them names the validator's report instead, and reads Waiting until a report saved after its last result passes; the player walkthrough skill publishes an MV/MZ page before validating it and republishes until its report passes, while other engines have no validator, so their saved page ends the task.
The registry reads a report again only when its file time or size changes, and one still being written counts as none; a task whose assistant never validates waits until it is dismissed.
A widths report with no measurement finishes the line width task as Done with its result Skipped, and the widths stay as they are.
A widths report for the current request that the app cannot use reads Blocked with its reason, whichever task saved it, and the helper's context status gives the assistant the same reason; an earlier request's report is ignored.
The [Application](../backend/dazedtl/api/server.py) records it in the [assistant task registry](../backend/dazedtl/translation/assistant_tasks.py) and strips it from the reply, so features keep their own requests, reports and validation.
The snapshot lists the records with the newest time an expected file was saved, read from file times only, and [assistantTasks.ts](../app/src/features/assistant/assistantTasks.ts) derives each task's display state from that and its feature's observed state, so the Project page list, the top-bar count and each feature's panel agree.
Dismissing marks a record abandoned: the task leaves the list and its feature stops showing Waiting until the next copy, while saved requests and reports stay.
Tasks copied before records existed list only while their feature still waits.
Output availability, application to runtime files, assistant QA findings, and package availability are separate observations.
Execution rechecks source, scope, destination, and ownership evidence.
Application receipts distinguish later fitting or QA edits from new outputs that have not been applied.
Release plans bind the profile's working-source index and original blobs; refreshing or expanding a source pass invalidates pending package plans without rewriting old runs.

Each task applies its own work and shows what it has not applied; no cross-task list reminds the user of skipped work, because the stages and tasks already show it.
Text tasks and Release apply saved output through the Guided action review.
Images' Apply to game opens a [PendingReview](../app/src/features/guided/workspace/PendingReview.tsx) whose content reuses Images' own review; Assistant-led's Image Manager keeps its own review, and Plugin files and Text QA apply their checked work in one click.
Its [hook](../app/src/features/guided/workspace/usePendingChanges.ts) prepares the preview from observed state through [pending.ts](../app/src/features/guided/pending.ts) and applies it under one action key with the preview's own one-use token, so a repeated click cannot start it twice.
Images restore in the Image Manager and plugin files in their workspace; applied Translate output has no restore of its own, since Git version tracking and Backups undo it, while Text QA, glossary and playtest fix batches restore from the History inspector, as below.
A text batch whose publication was interrupted or could not roll back raises a notice on every Guided task with its Review restore, because part of it may be in the game.
TL Inspector and Forge install from a Playtest tools sheet in Check's task header, where applied text is playtested, and an Ace game whose data is older than its `ace_json` gets Pack outside edits in the same header; both reuse the Guided action reviews and operation tracking, and the Project page stays about status, history, updates and backups.
The player walkthrough task sits with Release, since it produces player documentation.
The [text publication journal](../backend/dazedtl/translation/publication.py) freezes reviewed destinations and both byte versions before any runtime replacement.
The compatibility worker fits the text on the frozen candidates, then preflights and publishes the whole batch with verified backups and rollback attempts.
Interrupted publication retains exact authorized before/after hashes for another reviewed restore; conflicting newer runtime edits are retained.
Completed restores retire the recovered batch's notice in history; undoing a restore revives the earlier batch state without changing preserved receipts.
A batch restores on its own once no later batch still in the game changed the same files, and its restore puts back only that batch's entries in the Apply receipt, so a later Apply of other files stays applied; otherwise History names the later batch, which is restored first or, for an Apply, keeps the batch.
Reapplying saved translations discloses replacement of later runtime edits, independently of output availability.

Optional text QA retains the engine's project-scoped discovery inventory and findings, bound to current runtime text and original-source context.
One [QA policy](../backend/dazedtl/engine/data/skills/rpgmaker_translation_qa.md) makes the task README, each reviewer role's fixed brief, the worker brief and the copied handoff, so they cannot disagree about applying.
The coordinator runs four workers at once, each a fresh session given only its name and the worker brief, which holds every role and ends a run after a few bundles; it reviews nothing itself and never works under two names, so a check is another reviewer's own read.
Every brief also holds the game's notes, translation quirks and recorded decisions, and every printed bundle ends with the glossary entries whose Japanese it holds or whose English names one of its speakers, notes included, so no reviewer reads the task's context or the game's files; `next` prints the bundle it hands out, with the decisions recorded since the worker's last bundle, and `accept --next` accepts a result and prints the worker's next bundle, so a bundle costs a worker about two turns; once the run its `brief --worker` started has reviewed six bundles, `accept` tells it to stop instead, so no worker counts or claims a bundle it then gives back.
A new task builds on earlier reviews: each complete task keeps the lines it reviewed and left standing, which are the text it screened or deep-reviewed and the corrections editorial confirmed, as the game holds them once applied, less lines whose finding still waits to be applied, whose review was declined or that it reports as not reviewed.
The ledger is made under the task's lock, which a follow-up round holds while it reopens the task, and a task the app set aside, or whose findings another task made, keeps none.
A later task of the game makes such a line a target only once its Japanese or English changed, or a glossary entry or quirk governing Japanese it holds changed since that review, where a quirk governs the Japanese it quotes, a hiragana word of two kana only a line that is that word and a katakana one, such as a name, only where it is a word of its own; other lines show only as context, so a scene without a target is not read.
Deep-review reasons a line was cleared for and lint proposals rejected for the same text are not raised again, nor is a `text-fit` check under the Line widths it was settled with, while squeezed interface text and playtest observations not yet judged for that text always are.
When the user says the text up to an update was checked before, the project helper's `qa --prepare --since` takes the game's text as Git had it before that update, or at a revision, as reviewed in the same way, for that task and every later one of the game; `--everything` reviews every line, and preparing again without either goes on with the scope named last, which a `scope.json` beside the focus's tasks remembers, while the text is the same.
Finishing earlier tasks and newer observations leave a prepared task as it is, so preparing again with nothing changed resumes it.
The task preparing returned last is the focus's current one, which a `current.json` beside its tasks names; the helper's task commands refuse a task it replaced and name the current one, so an assistant holding an older README can't review, report or finish the wrong task.
A new task also starts with the decisions complete earlier tasks recorded, the latest per key, less one naming Japanese whose glossary entry or quirk changed since, and its lint proposes no glossary fix that would undo a decided rendering, so a settled choice stays settled.
`rebuild-deep` prepares its new task from the earlier reviews its source read, so the screen it reuses holds the same lines, and removes a task it made but could not fill; it compares only the text the two inventories hold and where it lives, not what QA derives from it, such as a line's mechanical evidence or the name of a text variable's quote marks, which an update may derive otherwise, and keeps the screen only while the current rules make the same screen bundles, so a change to what screening shows starts the screen over.
A screen whose reviewers declined items is finished too: the new task declines the same items into the same bundles and sets aside again what its source set aside as not reviewed.
Hints are not what screening shows: the new task packs its screen into the source's bundles and compares them without the risks and glossary terms items point reviewers at, which an update may word otherwise or at another length, as when screen items started naming only the glossary terms a line's English lacks.
Each task's ledger carries a version, so one an earlier version derived and cached is derived again; baselines, the game's text as Git had it, carry none.
Its inventory holds the text the engine translated, which keeps its Japanese in `_original`; a [preflight](../backend/dazedtl/engine/util/rpgmaker_qa_preflight.py) reports the Japanese that was never translated, in rows no translation holds (see [RPG Maker text blocks](#rpg-maker-text-blocks)), database fields without `_original`, custom data files and plugin parameters, so that gap is shown rather than silent.
Status, findings and the Text QA task name it as never translated and not reviewed, by file and plugin, never as a passing count.
QA neither reviews it nor blocks on it: reviewers judge translations, corrections apply only to the inventory's data files, plugin text goes through Plugin files' checked publication, and whether a plugin's text shows is evidence too uncertain to stop QA.
Plugin parameters that Plugin files keeps in Japanese on purpose, lookup keys the app protects and text its assistant found players never read, are not reported: the compatibility layer reads them from [Plugin files' saved findings](../backend/dazedtl/plugins/service.py) while its scan matches `js/plugins.js` or the file is settled, and the preflight leaves out a parameter only while it holds the value its finding was about, so text Plugin files never examined or left undecided is still reported.
The report is the task's `preflight.json`, which the pointer's immutable evidence leaves out, and status and findings take their counts from it, so it can change without restarting review.
It records every plugin setting it read with its plugin's reach, so while a task is current the compatibility layer reapplies Plugin files' decisions when they change without reading the game again; preparing again reuses a task with its checkpoint but reads the whole report again, since plugin settings and code change it without changing the inventory, which hashes every data file.
For each custom file and plugin, [reach](../backend/dazedtl/engine/util/rpgmaker_qa_reach.py) reads the game's code as text: an event calling the plugin's commands, an event script or running plugin using what it defines, or the plugin changing the game's screens or page itself means players may see its text, and none of these means they don't now; a custom file takes its readers' reach, and one no turned-on plugin names is unread.
Copied tasks do not imply completed work, and a saved discovery stage does not certify current QA passed.
Applied corrections bind to the specific task and pass the engine's correction and regression checks on disposable copies before they are published.
The [engine](../backend/dazedtl/engine/util/rpgmaker_qa.py) checks each correction when a reviewer submits it, and every finding again when findings are made, against what the post-apply regression rejects: a mechanical flag the correction adds, a line count its pointers can't hold, or more rows than its box shows.
A task keeps the Line widths it was prepared with, and each place a correction reaches gets the box the [fitter](../backend/dazedtl/engine/util/rpgmaker_rewrap.py) gives that text: its width, the message rows for a message, and the rows of a fixed window such as a help window.
A correction with a line wider than its box is fitted as translation fits text, and findings store the fitted text, so the page shows what the game gets; a message over several commands is fitted the same way and spread over them, while other text over several commands, such as a comment, keeps its line count, so a line wider than both its box and the current text is refused instead.
Text a fixed window cuts off even fitted gets a `text-fit` check, so a reviewer shortens it.
A choice's help counts its rows as its window shows them, with the rest of its comment: the game's own rows, such as "(1/3)", and its other translated parts, which the inventory keeps beside each part ([rpgmaker_blocks](../backend/dazedtl/engine/util/rpgmaker_blocks.py) `help_layout`), as Line widths checks them.
A correction of a text variable (code 122) goes into its script string with the escapes [translation writes there](../backend/dazedtl/engine/util/rpgmaker_script_strings.py), so a backtick, `${`, `#{` or a message code's lone backslash can't end the string early or interpolate, while an interpolation the target's current text runs keeps running, and is wrapped to the list width as the fitter wraps a text variable; between quote marks translation never writes, a correction may not add a quote mark.
Findings keep such a correction as its reviewer wrote it and the escapes go in once, as it is written, since a line break right before `[` or `<` would read as a code such as `\n[1]` once escaped; a correction with one is refused.
The Text QA page shows its Japanese, current text and correction as they read, without the script string's escapes, the correction wrapped as the game gets it, so an escape never reads as a change.
So no finding can roll an apply back; an English number word or ordinal may stand for the source's number, as in "First Stratum" for 第1層, plus signs and thousands separators don't count, and a stat or gold abbreviation such as TP24 or 100G doesn't hide its number.
A mechanical flag forces deep review only when it can be a defect: a number the English adds or changes, a number above ten it drops outside ordinals, kanji numerals and idioms such as 1番, or a control code it lost, RPG Maker's %1 placeholders and name window codes such as `\nc<Alice>` included.
Preparing QA from the app or the engine's command also captures the game's interface screens: the [capture](../backend/dazedtl/engine/util/rpgmaker_screens/capture.cjs) runs the game in a hidden game window, and its [harness](../backend/dazedtl/engine/util/rpgmaker_screens/harness.js) opens the title, menu, item, skill, equipment, status, shop, options and battle screens with the starting party holding everything, measuring every label with the game's fonts.
The [game window](../backend/dazedtl/engine/util/rpgmaker_window/launcher.cjs), which the release playtest below uses too, serves the game folder read-only through a private protocol, finding files whatever their case as Windows does, to muted offscreen windows of the app's Electron in an in-memory session with no network, pop-ups or permissions, so nothing reaches the game's saves; on Linux it needs no display and reaches the GPU through EGL.
It replaces a window whose game crashes, hangs or stops drawing, where the harness carries on without the screen or stop that stopped it, and a game that never starts on the GPU plays again with SwiftShader.
Text the game squeezes or cuts off goes to deep review with an `interface-fit` check naming its captures, and choice lists are captured when the game cuts one off; text QA holds no line of, such as a plugin's menu command, is reported, and so is a game the capture could not run.
In Guided, that text goes to Plugin files when it is found in a plugin file, and QA's record in the History inspector shows where each label stands there.
Assistant-led has no Plugin files task, since its assistant writes the game's files itself: [`qa` status](translation-contract.md#project-helper) lists the labels for it to shorten and capture again before apply, because corrections that change the game's text make the next preparation another task.
Each capture is a round the task records with a digest of the plugin list and plugin code it ran with, which change the screens without changing the inventory; preparing a task again captures again once they changed, keeping its review, so Plugin files' shortened labels drop off and the labels still too long go back to it.
Text the new round finds squeezed goes to deep review as an observation, unless an earlier round found it squeezed, and a complete task goes back to deep review for it in a follow-up round like an observation made after deep review, so a plugin change needs no new review of the rest; earlier rounds stay while review bundles may name them.
This can't remake a finding that is in the game: applying corrections changes the inventory, so the next prepare makes another task, and a reused task holds the text QA reviewed, with nothing applied or every correction undone.
Until the follow-up round ends, later tasks don't build on the reopened task's reviews, since its findings are made again.
For a correction of such text, editorial reads the screens captured again with the corrected data served in place of the game's, so reviewers judge what players will see rather than character counts.
[Database checks](../backend/dazedtl/engine/util/rpgmaker_qa_checks.py) also force deep review, with evidence the deep item shows: two entries of one database whose different names share an English name, and a battle message that reads wrong once RPG Maker adds the battler's name, which MZ puts only where %1 is and MV writes directly before the message.
Deep bundles group items by scene, print each scene once with the lines its items' screen evidence names and list at most twelve occurrences an item, and `show` prints any bundle as compact text; on the Arina run that cut deep review's text from 14.4 MB to 3.3 MB.
An item stays in the bundle that already prints its scene even past the bundle's size, since another bundle would print the scene again.
Deep review starts while screening continues: once enough screened clusters are ready, with their target bundle and motif reviews accepted, the engine opens deep bundles for them, and when screening ends, and again before deep review ends, it opens the rest and reopens a cluster whose screen evidence grew after its deep review, with that review beside it; the latest review counts.
A reviewer that notices a concrete defect outside its own items, in nearby commands, the context view, another scene or after its bundle was accepted, adds an observation to a result, or the coordinator records one with `observe`: one inventory line, which may be named by its database field or event command, the number `show` gives each scene line, and a one-line reason.
The engine refuses an observation that names no single line or a line the result judges itself; the line becomes a deep candidate with that reason as screen evidence, in the next early batch while screening continues and at once during deep review.
An observation made after deep review sends QA back to deep review for a follow-up round once the current stage's bundles are done; the sweep then offers only lines no earlier sweep did, and findings are made again with the IDs unchanged findings had, so earlier editorial verdicts stand and only new or changed corrections get an editorial round.
The engine assigns, releases and times workers: `next` moves QA to its next stage once a stage is reviewed, hands a bundle whose worker has not been seen for twenty minutes, or three times a typical bundle, to the next idle worker, and `status` estimates the time left from the measured time per item and how many bundles were in review at once in QA's latest half hour of work.
It counts bundles rather than worker names, since one session taking turns under two names reviews one bundle at a time; when bundles wait while QA reviews one at a time, `status`, the project helper's next step and the Text QA activity line say so.
A reviewer that will not review an item declines it with a one-line reason, and the engine accepts the rest of its bundle and moves the declined items to a bundle of their own.
Workers on one AI helper share its boundaries, so only a worker on another helper can claim that bundle; a worker names its helper on its first claim when it is not the coordinator's, and keeps it.
A reviewer may decline one lint proposal, sweep candidate or motif variant of a family by its own ID and review the rest, so a family that mixes scenes needs no rejection of lines it did not read.
A coordinator declines items it read in a bundle no worker holds yet with `decline`, which moves them to a declined bundle and the rest to a new bundle in its place, so its workers never see them and the decline is recorded as the coordinator's.
Declined items are set aside once a second helper declines them, or when the assistant reports that no other helper will take them, which `next` can also do when the rest of their stage is reviewed, so content is never classified or excluded in advance.
Before screening ends, text whose every screen target was set aside gets a target in another scene that shows it and no reviewer declined, in follow-up screen bundles, so a declined scene leaves out only the text no other scene shows.
Set-aside lines stay out of deep review and of every correction but automatic lint fixes, as do observations on them, and findings report them once as not reviewed, naming the workers that declined them: every line of a scene no screen reviewer read, and each occurrence of text no reviewer judged anywhere; text judged in another scene keeps its corrections outside the declined scenes.
The read-only context view leaves out every scene a reviewer declined and every scene a declined deep item was screened in, waiting or set aside, except for a worker that names itself and whose assigned bundle prints the scene, such as the reviewer that claimed it.
Screening is checked rather than trusted: another reviewer screens at least a quarter of each reviewer's scene and line targets again, starting with its first bundle, and never by the reviewer that screened them.
Whatever either screen reports goes to deep review, which waits for a bundle's check, and a reviewer whose checks found at least two problems it missed, and more than it found in those lines, has every bundle checked.
Checks add no coverage, so `status` counts them apart, lines a check declines count as unchecked and send another bundle to be checked, and the activity line counts checks as screening.
Before screening, [lint](../backend/dazedtl/engine/util/rpgmaker_qa_lint.py) proposes exact fixes for known mechanical families: spacing after ♥, stray letters for the small っ, dakuten apostrophes on real words, list items merged onto one line, quoted titles that no longer match their title, duplicated labels and level-tag spacing.
Screen lines show those fixes, so screening concentrates on meaning and voice.
The families lint marks automatic, spacing after ♥ and stray letters for the small っ, need no reviewer: their fixes were right on every line they matched in ten released games and change no line break or code.
QA accepts them on every translated line, lines reviewers declined included, and [MV/MZ translation](../backend/dazedtl/engine/modules/rpgmakermvmz.py) already applies them to each new line before it is wrapped.
The other families' proposals are reviewed as a group in small items by scene, because an apostrophe can be a moan's or a slur's, a title needs the whole game's titles, list and label fixes change line breaks, and level-tag spacing matched no real defect there.
Accepted fixes become findings and also apply on top of a deep correction of the same line.
Lint's glossary family keeps the game's glossary enforced after translation: its [scan](../backend/dazedtl/engine/util/rpgmaker_qa_glossary.py) reads the task's glossary against the inventory, which pairs each line's Japanese from the engine's `_original` with the English the game shows, whatever profile or method translated it.
Each glossary row claims its span of the Japanese, longest first, so a term inside a longer one is never checked on its own; base glossary rows only claim, terms written in hiragana alone are skipped, and a term that continues a longer word of its own script or of letters and digits, as パン does in パンツ, belongs to that word.
A line uses a term when its English holds the term's words in any order, allowing plurals, verb endings, a final possessive, small words such as "of", a leading article, a trailing "(…)" qualifier, either part of "Name, Title", a name's people or adjective such as "Shikinowan", a person's people such as "police" for Policeman, and either name of a katakana name the glossary gives a full English name.
A line that misses a term gets a proposal only where its rendering is found: the whole English of a nameplate, actor name or database name whose Japanese is only the term; the words most like the term's own, keeping its first letter, written as a name, and neither an abbreviation nor part of a hyphenated word; a name that keeps one of the term's words and writes the rest in romanized Japanese, as "Crag of Yomi" does Underworld Crag; or a rendering another line of the term was found with.
The fix replaces every place the line writes that rendering and keeps a line break it crosses.
A line without a rendering, mostly a name said as "you" or an ordinary word written like a term, such as 回復 beside a skill named Heal, is left to the screen reviewers, whose lines list the glossary terms they hold.
On ten translated MV/MZ games the retired Guided Glossary check flagged 7,631 lines for the user to sort, 22 to 4,216 a game; the family proposes 150 fixes, 0 to 107 a game, nearly all renamings and drift such as "Shinnaisamu" for the glossary's Sinnaysam, and it replaced QA's database glossary check, which sent 175 database texts to deep review, mostly 回復 in descriptions.
Group reviewers accept a proposal where the line names the glossary's character, place or thing; none is automatic, since about one in ten there was a judgment call, such as a state named Defense the glossary calls Defend.
The glossary is part of the task's context, so a row changed after translation is read the next time QA runs, in a new task, and a glossary fix batch the retired check applied still restores in History.
A deep correction of a problem that recurs word for word can carry a sweep rule that reproduces it exactly; after deep review the engine finds every other line of the same display shape the rule changes, and reviewers accept or reject those as a group before findings are made.
A defect of a whole scene, such as narration that turns present partway through, gets a scene correction instead: one deep review changes several lines of one of its item's scenes, each with its own text and in every copy of that scene, as one finding that applies and undoes as a unit.
Each line is named by the event command the scene prints for it and its exact current text, passes the same checks as any correction, and is refused in a scene or item a reviewer declined; a later decline drops the whole correction.
Editorial reviews the lines together and revises them line by line; once it accepts a scene correction, that correction replaces any other correction of its lines, which editorial saw as a conflict, and two scene corrections cannot share a line.
An editorial stage then confirms every reviewer-written correction: a reviewer accepts, revises or withdraws it, and a fluency, voice or wordplay correction goes only to a worker that wrote none of its bundle's corrections.
Before each round, a consistency check marks corrections that contradict the translation quirks, a structured label, each other or the decision log, where reviewers record shared choices such as narration tense; a contradiction comes back in another round until it is resolved, each round judging the text the previous one left, and after three such rounds it is reported as unverified instead of applied.
A recorded decision also wins over the glossary row it disputes: lint's glossary family leaves a line whose decided rendering its fix would remove, as on Fuuma Chronicle, where the glossary's Demon King's Kunai otherwise fought the decision for Demon Lord through every round.
A revision replaces the correction the reviewer saw with its lint fixes in it, so only the automatic families apply on top of it again, and a withdrawn correction leaves its line the lint fixes it was given as a remnant that editorial judges like any finding when a conflict shows it.
Slips in the Japanese source have findings of their own: a Show Text header's face and name, which must be a face the game already shows, a database text whose number its own entry contradicts, which may change only to a number that entry holds, and an MZ battle message the battler-name check found without %1, which may gain only that %1; apply and regression check both like any correction.
A [header check](../backend/dazedtl/engine/util/rpgmaker_header_check.py) finds likely slips in Show Text headers before any review: a face shown once or twice for another character, a speaker calling out to themself or naming themself with an honorific as another speaker in the scene does, a first-person pronoun only another speaker in the scene uses, and a nameplate on a box styled like the game's unnamed sound effects beside an unnamed spoken line.
Each rule learns the convention it checks from the game's own boxes and flags only rare breaks of it.
Each flag on a line the inventory holds is a `show-text-header` check that forces deep review like the database checks, with the check's reason; a header the translation already gave another speaker is not flagged, so a fixed slip does not come back, and a flag the setup assistant kept gets this second look after translation.
On Arina and the Succubus Curse, whose translation, a manual fix and release QA corrected 24 headers, the check raised 14 flags on the Japanese source, all slips: 9 of those 24 and 5 no one had fixed.
Across 16 other games in one translator's library it raised 6: three clear slips, two likely ones and a deliberate change of register.
Those games ruled out cues that worked on Arina alone: an unnamed spoken box between named ones (15 flags and 11 slips on Arina, but about 200 elsewhere, nearly all narrators, crowds and off-screen voices left unnamed on purpose), a name called out without another speaker using it, a placeholder such as ？？？ and a face shown repeatedly with an alias.
Arina ruled out voice files before a box (its voice folders also play before sound effects), every named sound effect (21 flags, 1 slip), narration under a nameplate (33 flags, 2 slips), a reply after someone addressed a third character (4 flags, 1 slip) and identical lines whose nameplates differ (all deliberate labels).
Release QA applies its finished findings without asking: [qa](../backend/dazedtl/translation/text_qa.py) `--apply` in the project helper, or Apply on the Text QA page, previews and executes one `qa_apply` text batch, so History can restore it, and then saves a checkpoint commit; Undo puts back one applied correction as a `qa_undo` batch of its own.
Apply again applies an undone correction as a `qa_apply` batch of its own; like Undo it checks each line against the text QA reviewed, so edits elsewhere since the first apply do not stop it, and a changed line does.
After an apply, a follow-up round's new findings and open questions make the task wait again, and Apply takes only corrections never applied, leaving undone ones to Apply again.
A step reads as running until its worker exits, because the checkpoint waits for that worker, and a checkpoint that did not finish runs again from Save version beside its failure.
History's inspector restores a QA batch through the restore review, so undoing every correction at once needs no QA command; a batch restores only once the newer batches are restored, since each restore needs the text as its batch left it.
Apply waits while a playtest or context question is open, which the user answers on the page by keeping the line or using the reviewer's proposal; a question always carries a proposal, since one the user could only keep would ask for nothing, so a defect no correction can fix within apply's checks is reported as not corrected instead and never waits; no QA command writes game files itself, and pushing and publishing stay the user's.
The [Text QA page](../app/src/features/guided/workspace/tasks/check.tsx) starts QA in one click that prepares the task and copies it; it and Assistant-led's Text QA tab share [the task's view](../app/src/features/guided/TextQa.tsx), which shows the engine's activity line and stage strip while QA runs, a Needs you card for open questions, an apply that failed and rolled back, and once done the corrections by category with Undo or Apply again.
Each correction and question says what is wrong in the reviewer's one plain sentence, which deep review requires of every review that changes or reports a line (at most 120 characters, without codes or pointers); a task made before that shows the start of the reviewer's evidence with Show more.
What QA did not cover stays off that page, since each part has its own owner: the engine sets aside declined lines no reviewer on another helper took, the release playtest lists never-translated Japanese with its reach and the task that translates it, Plugin files, or in Assistant-led the assistant, takes squeezed plugin labels, and a capture that could not run is a diagnostic.
Guided's History inspector keeps the record: inspecting the activity that prepared the current task shows the [report](../backend/dazedtl/compatibility/text.py) `qa_report` reads, with the lines not corrected and why, the reviewers' full evidence and editorial notes behind each correction and question, the declined lines, the never-translated Japanese by file and plugin with its reach, and the screen text QA can't correct.
A QA task is named by what it reviews, as [saved work](#persistence-and-settings) is: the text its inventory holds rather than the evidence QA derives from it, the context, focus, screen packing and earlier-review scope, and [rpgmaker_qa](../backend/dazedtl/engine/util/rpgmaker_qa.py)'s `QA_RULES_VERSION`, so an update leaves saved QA work current.
Bumping that version, only for a change that makes saved reviews wrong or unreadable, stops review in a task prepared before it, which reads as outdated, and preparing QA again makes a new task that builds on finished ones.
A finished task keeps its results under any version and applies, undoes and applies again, since apply checks each correction with the current rules.
Tasks that 2.24.0 and earlier made named a hash of QA's code files instead; they count as the first version, and preparing finds them again from what their task.json recorded.
A prepared task the app can't read or trust, such as one whose files lost the app's access, reads as blocked with the reason, never as not started; Run QA again, or the helper's `qa --prepare`, renames it beside the others with an `-unreadable` suffix and prepares a fresh one, and the helper's status names its folder and error so an assistant that can restore access continues it instead.
An Assistant-led MV/MZ or Ace game gets the Guided game workspace for this the first time its assistant uses QA, and its checkpoint reuses the runtime manifest of its last one.
There the starting prompt runs QA through the helper after the checkpoint, the Text QA tab appears once a task exists, and Progress takes QA's stage and counts from the task while it runs and points out open questions; whether QA is done stays the assistant's report, since new translation after an apply reopens it.
The top bar's assistant task count and Progress show the questions QA waits on, and [notifications](#notifications) call the user back for new ones.
The release playtest, part of Guided's Text QA task for MV/MZ and an Assistant-led tab once it has a report, checks the game's files and then plays the game; [its design](text-qa-redesign.md#release-playtest) holds the decisions.
In Guided the copied QA task [adds its loop](../backend/dazedtl/translation/playtest.py) for MV/MZ games, so the assistant runs both, and the Text QA page shows the playtest's panel below QA's, with its problems in a sheet.
That copy names the playtest's report as the file it saves last, so once QA's corrections are applied, or it found none, the task still waits in the assistant task list, and Next stays quiet, until no playtest runs and the latest report is of the game as it is with no text problem left for QA, and either played the game or names no crash for the assistant to fix, as for a game without its engine's scripts, whose Playtest panel then reads Blocked with the reason.
While the copy waits, its Playtest panel reads Waiting, not Outdated after QA's or a fix's changes or Blocked by a crash the assistant fixes; once no copy is at work and the check is not settled, as for a copy made before the playtest joined the task, the page leads with Run QA again, which copies one that is.
The Project page marks Text QA done at the same point, and for VX Ace once QA is applied or clean; a copy made before the playtest joined the task leaves the assistant task list with QA.
Its [static checks](../backend/dazedtl/engine/util/playtest/checks.py) report data files and plugins that would stop the game, Japanese left in translated text, but for a control code's argument such as the font of `\fn[和風]`, and placeholder glyphs, text never translated through the preflight above, battle messages, System terms and event pages that lost a `%n`, battler name or shown code their `_original` has, and Japanese strings in plugin code with their reach, which [code.cjs](../backend/dazedtl/engine/util/playtest/code.cjs) reads by compiling each plugin with V8 and parsing it with Acorn.
Strings in plugin code and plugin settings that Plugin files keeps in Japanese on purpose count only once the tour sees them drawn.
Descriptions longer than the standard help window's two lines only tell the tour where to look, since a plugin may draw the help its own way or give the window more lines: one is a problem once the tour sees that description's own text run past the bottom of its window, one the tour shows otherwise is left out, and one it never shows is a gap.
The [tour](../backend/dazedtl/engine/util/playtest/harness/main.cjs) plays the game in the same game window as the interface capture; [its page script](../backend/dazedtl/engine/util/playtest/harness/page.js) records errors, Japanese drawn, text past its window and messages, each kept once its bitmap is on screen and captured, and the database entries help windows show, while it plays the title, New Game and its opening, every menu screen with every item and skill in hand, a save and a load, a shop, a battle, plugin screens and the assistant's stops.
The `release_playtest` tool operation [runs it](../backend/dazedtl/engine/util/playtest/run.py) and keeps the last three reports in the workflow folder; a report is current while the game's data, plugin list and plugins are as it played them, and each counts the problems fixed since the one before and marks new ones.
The stops an assistant gives are saved with the project, and every later run visits them.
The `playtest_fix` operation plays the game with the assistant's [fixes plugin](../backend/dazedtl/engine/util/playtest/fixes.py) served in place of the game's files, with one line in `js/main.js` loading it after the game's plugins; when the play passes, it writes both as a text publication, which may add a file and whose restore takes it out again, and the play becomes the latest report.
The working copy changes nothing in the game on its own, so the helper's status says when the game runs other fixes than the copy, as after the copy was emptied, and how to put the copy in or take the game's fixes out.
Like DazedTL's other files, both join every patch's manifest once the game has the plugin, so every patch carries the fixes whichever method wrote the manifest, since a manifest without them would leave the fixes out of the patch without an error; the helper's `playtest --fix` then saves them as a version of their own, a checkpoint in Assistant-led, and QA's apply and the playtest's fix each wait while the other's changes are in no version, since a version takes every change in the game, as Fuuma Chronicle's QA version took fixes written before it on 2026-10-20.
A checkpoint without a prepared backup or Git copy of `js/main.js` takes its original as the file without the loading line, and every checkpoint refuses a main.js that loads fixes the patch lacks, or fixes no main.js in the patch loads.
A game update whose release wins a hunk of `js/main.js` gets the loading line back after the merge.
Plugin files reads which Japanese the latest report saw drawn and asks its assistant again about such text it kept, once, with that evidence; it never lists the fixes plugin.
The `layout_capture` operation, `playtest --layout` in the project helper, plays only the title, New Game and opening, then shows English exactly as wide as the given widths in the message window with and without the first actor's face and in the item screen's help window, measuring each line against the room the window gives it and capturing each; it keeps its own last three reports, so it never replaces the playtest's, and confirms a setup task's measured widths on screen where the task had improvised a browser session.
Problems in lines text QA reviews go to QA as observations of a `playtest` worker: QA prepares its task with the current report's findings, and a playtest that ends while a task reviews records the findings it lacks.
Each such problem reads as in review, reviewed, waiting for QA's next round, or not in QA's review, outside the QA focus for a narrower one, when no one line of its task's inventory has that name, so a database focus never waits on dialogue.
A task keeps the user's answers to its questions, where its ledger reads them; QA's next read copies in the answers 2.24.0 kept in the game workspace's `text-qa-choices.json`, which stays for going back, where the task holds none.
A line a new task left out because an earlier deep review judged the same text for the same reason, finding it right or beyond correction or the user keeping it, reads reviewed, and the task keeps those observations apart so preparing again does not take them either; a line that review corrected comes back while it keeps that text, as when editorial left the correction unverified.
A line the task observes or judged reads waiting once its English is no longer the text the task read, as after its correction is in, so a corrected line the next play still flags goes to QA's next round.
A line a complete task corrected to no effect, still holding the text it read, reads waiting too once the game's other text changed, since preparing again then makes a task that takes it back; while nothing changed, preparing again resumes the same task, so it reads reviewed.
Observations of one line count apart by reason: a playtest finding joins a reviewer's on the same line, and the same reason again adds nothing.
So a problem reads in review or reviewed only while its task holds the line for that problem's own reason, and one on a line held only for another reason waits for QA's next round.
After QA's apply, the copied task's assistant prepares that next round itself for waiting problems, and the helper's playtest status counts them; the Text QA page points them out, with a primary Run QA again only once the copy is no longer with its assistant.
Findings never make another task: preparing again, as after a fix, a Plugin files apply or shortened labels change the plugins, resumes the task with the observations it holds and takes findings it does not hold yet, at once while it reviews and in a follow-up deep round once it is complete.
QA's state says when only the game's plugin list or plugin files changed since a task was prepared; while the copy is with its assistant, which prepares again after its own fixes, that task reads Waiting rather than Outdated, and otherwise Outdated names the plugins rather than the text.
QA, the playtest and opening the game are optional, with no QA or playtest prerequisites for navigation or Guided Release.

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
Give `useAction` the application as its `observer` when its completion needs updated observed state: it waits only for an observation of API mutations the action began.
An earlier mutation, such as the window-focus recheck or a waiting image task's report check, observes its own result without holding up the next action.
Reserve `application.refresh` for an intentional re-read, such as an explicit reload control.
Views that show their own replies before the next observation, such as Plugin files and Image Manager, use [`useObserved`](../app/src/state/useObserved.ts): a newer snapshot replaces a reply during render but waits while unsaved edits or actions build on the current revision.
They start from the observed state when the snapshot already has it, so revisiting them reads only what is missing.
Do not attach an unconditional whole-project refresh to every button.
An open project stays observable while no app worker is active so external assistant reports become visible.
Observation ends only when the backend stops or is incompatible; any other failed read is tried again after a growing delay, so a transient backend error cannot freeze progress, and the next successful read clears its error.
Returning to the window rechecks outside edits through `workspace_recheck`, which reinspects the images being worked on (working copies, the selection and applied images) against their cached file signatures; as a mutation it is followed by a fresh observation, so every feature sees the result without its own refresh.
It also imports a report saved for a copied image task, including a finished task's report the assistant saves again for the user's redo requests, and the Image Manager runs the same import every few seconds while a task waits, so results arrive while DazedTL keeps the focus; a rejected report is remembered by its hash, so it is reported once and retried only after the file changes.
Guided reports are read by the observer, and plugin reports are validated by the project helper's continue command the assistant runs.
Saved run indexes keep these observations small; full request bodies are checked at execution/inspection boundaries.
Request rows stay out of observations: a run's [process summary](../backend/dazedtl/compatibility/process_view.py) carries each file's request counts, states and the Batches holding its submitted requests, the inspector's request groups, and the first requests needing attention.
Its request revision changes whenever a displayed request does, so an open inspector reads its page again.
The run log also stays out, so an open inspector reads the full run once more when the run's status changes, keeping the previous log visible until it arrives.
New observation work must use bounded summaries or cached derivations with explicit invalidation.
A poll checks every saved run, so a cache it reads on every poll must keep that whole working set: one bounded below a long run history rereads every file on every poll.
File digests use [`Digests`](../backend/dazedtl/translation/files.py), which drops only entries no read has used for a while, and run views answer from each folder's listing instead of resolving every output.
Do not add whole-game parsing or full request-history reconstruction to a polling snapshot.
Requests, the project helper's included, run one at a time behind the lock every snapshot needs, so work that takes seconds on a big game starts an operation worker instead of running in the request.
Measure nontrivial additions with representative generated data; keep authoritative source, artifact and spending checks at their execution or explicit inspection boundaries.
Cached display state never authorizes paid work or file publication.
Each Guided observation reuses ownership, run metadata and name-reuse reads within that observation.
It lists each game and working-copy folder once, and reuses a listed file's digest across observations while its stat signature holds, so routine polls neither resolve paths nor reread unchanged files ([ObservedFiles](../backend/dazedtl/translation/files.py)).
A file changed within the last two seconds is read again, because a second change within one clock tick can keep its signature.
Action guards and run inventories reuse digests the same way through the engine's [file_digest](../backend/dazedtl/engine/desktop/backend/project.py), so an estimate's preview and confirmation and the Batch preparation after it read each game file once.
A run copies its input folder once and the engine's working inputs share those files, since runs only read them.
A poll starts no process per file: Other event text reads every original it has not hashed yet through one Git process, and Git status runs its full inspection only after Git's metadata changes, asking `git status` alone every few seconds for the working tree ([git_status_cache.py](../backend/dazedtl/translation/git_status_cache.py)).
The bounded [history display cache](../backend/dazedtl/compatibility/observations.py) retains compact plan headers, process summaries and each run's grouped requests across observations; the inspector's request pages read the same grouped requests.
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
Whether saved work is still current has one rule, explained in [freshness](../backend/dazedtl/engine/util/freshness.py), and every kind of saved work decides it there.
The [previous-release QA check](development.md#previous-release-qa-check) fails when a change breaks the previous release's Text QA tasks without bumping their version.
The storage helper validates the result, retains the original bytes in a backup, and replaces the file atomically; unsupported or invalid formats are left untouched.
Project opening and selection publish their in-memory ownership only after backend persistence succeeds; presentation-only navigation does not change that ownership.
Removing a game from the recent list hides its registry record instead of deleting it, so its runs, Batches and assistant reports keep their owner, and opening or selecting the game again shows it with its work; older versions ignore the flag and list the game, so it needs no new format version.
Engine-owned settings and run formats remain the adapter's responsibility.
Diagnostics record only fixed metadata and relative code locations, excluding exception messages, payloads, and raw stderr.
They keep only failures the interface reports generically (internal and storage errors, abnormal backend exits, renderer failures), so explained refusals, clean shutdowns and relayed backend errors cannot push them out of the bounded report.
Hangs throw nothing, so a [watchdog](../backend/dazedtl/watchdog.py) records them: a backend request still running after 30 seconds, since every later request waits behind it, and a preparation or tool action without progress for a minute.
Each record holds where the stuck thread waits, with runs of standard-library frames shortened to the call into them and the wait, and a second record says how long it took once the work moves on.
Workers open the backend's log only to append each record, so the backend alone rotates it; a backend stopped at close names the oldest request still unanswered.
A worker's standard error goes to its run log or nowhere, so a worker records its own failures the interface shows generically, and any error nothing in it handled, as a worker error named by its action, through the [diagnostics](../backend/dazedtl/diagnostics.py) hooks and the engine workers' [reported failures](../backend/dazedtl/engine/desktop/backend/worker_failures.py).
The report names the checkout revision and whether tracked files changed, since code locations resolve only against that revision.

Connections and preferences share one atomic record in workspace `settings/settings.json`.
The Settings editor retains its session while hidden, so returning preserves its current view and fields without another initial settings read; the sidebar marks Settings while that hidden draft is unsaved.
Saved secrets never enter renderer responses or recovery drafts, and model drafts are bound to connection IDs.
The public preference schema contains language, model, per-model request/pricing options and GameUpdate's defaults, which stay among the engine values; legacy formatting and other engine values are retained privately through a backed-up versioned upgrade.
The adapter materializes legacy settings only before engine actions and checks the original provider route before resuming saved runs.
Connection checks are model-list requests, with bounded reads, no redirects, and no generated text; Settings runs one after saving new or changed credentials, and again on request.
Provider presets declare their transport protocol independently of their identity.
Kimi keeps OpenAI's Live and Batch formats under its own identity, so its Batches carry Kimi's eligible models and price factor from the [engine's Batch adapters](../backend/dazedtl/engine/util/batch_providers.py) and [cost rules](../backend/dazedtl/engine/util/provider_costs.py).
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
Its catalog download, address lookup included, ends after five seconds so the resolver answers before its caller stops waiting; past that, rates come from the saved catalog or the built-in defaults.
Guided and Assistant-led snapshots match estimates on prices already looked up and never run the resolver; preparing, reviewing and approving work look prices up.
Each model's last lookup is kept in the [model cache](../backend/dazedtl/compatibility/model_defaults.py), so snapshots after a restart still know it, and settings that differ only by prices not yet known read as unchanged; the model menu looks a model's prices up before it switches.
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

### Notifications

[WorkAlerts](../app/src/app/workAlerts.ts) reads every observation the store publishes, outside rendering, so a window in the background still notices; the first observation of a game only notes where its work stands.
It calls the user back once for work they started that ran at least ten seconds and then ended or waited for approval; steps that follow each other within four seconds, such as Set up's, count as one piece of work, and an approval given in the window starts new work.
That is every Guided run and step; an Assistant-led game's helper steps belong to its assistant, so only its API runs and Start over count.
It also calls them back when a copied task leaves waiting with the same copy, which a dismissal never does, when text QA has new questions, and when an Assistant-led run is blocked, done or waiting for an estimate's approval.
The choices are a browser-profile preference read by [notifications.ts](../app/src/app/notifications.ts), which plays the sound itself.
A chosen sound file is kept by the main process in the app profile ([sound.cjs](../app/electron/sound.cjs)), only after the interface has decoded it, so an unplayable file leaves the current sound; it plays for at most ten seconds.
The main process shows the desktop notification only while the window is not focused, except for the Settings test, and lights up the taskbar entry; regaining focus or closing clears both, since Windows starts a bare Electron for a notification clicked after the app has closed.
On Windows, notifications show under the Start menu shortcut that carries the app's ID, so the main process gives the launcher's DazedTL shortcut that ID and a fixed toast activator; Electron also writes an `Electron.lnk` beside it at a run's first notification, which opens a bare Electron, so the main process removes that shortcut once it appears.

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
On Windows every copied task opens with a [note](../backend/dazedtl/translation/helper_command.py) naming DazedTL's own Python with `-X utf8` and its bundled Git, because a fresh Windows has neither on `PATH`, only the Microsoft Store placeholder for Python, and Python writes pipes in the ANSI code page, which cannot hold the Japanese an assistant's own scripts print.

An assistant may run elevated, for example from an administrator PowerShell, and on Windows the files it writes then belong to Administrators.
The app's normal session can still open them where the folder grants the user access, but not where it grants access only to each file's owner.
Python's `mode=0o700`, which `tempfile.mkdtemp` and `TemporaryDirectory` use, makes exactly that owner-only folder on Windows.
So a folder that stays in the workspace, a game or an output folder, or whose files move there, comes from `new_folder` or `staging_folder` in the [platform layer](../backend/dazedtl/system.py), and keeps the permissions of the folder it is made in; tempfile remains for scratch that nothing moves out of.

A compiled plan freezes sources, full context, field constraints, provider parameters, rates, and connection identity.
Its plan.json keeps each long context text that repeats, such as the system prompt every request and its provider payload hold, once under its hash ([plan_file](../backend/dazedtl/translation/plan_file.py)), which made a 2,648-request plan 55 MB instead of 165 MB.
Reading it rebuilds the identical plan, and the run's record and approval bind the file's exact bytes; plans saved whole before this keep loading by their digest.
A worker reads its plan once and rereads only the run's record each time it polls a Batch.
Tracked game-source dependencies bind to their original-branch blobs; untracked source exports, project guidance and the plan file bind to their exact bytes.
Both API transports consume the same logical request builder.
Request IDs, speaker/scene context and protected tokens survive adapter conversion.
Organize derives version-two plans from engine-neutral source units that Len's extractor saves, so parsing and injection stay in Len's per-engine tools and the assistant never rewrites the game's text.
Organize and compile start such an operation: the app checks drafts, ownership and the settings the run freezes, and the [run compiler](../backend/dazedtl/translation/run_compiler.py) groups the units, compiles, prices and saves the run in its worker, since thousands of requests take tens of seconds; the helper waits and replies with the run.
Approving an estimate checks its sources, scope and baseline in the app, and the run's worker compiles every request again and compares them before it sends anything, so a big plan never holds the app's other requests while that runs.
A census the tool takes from the prepared source backup decides scope; organize --complete requires its coverage, so the assistant's extractor can't narrow it.
An Assistant only run can mark requests declined; an API run compiled from the same plan finishes them, and the declined run reads them as accepted once their results exist.
Version-two source plans require per-line text types and explicit nullable speakers.
Unknown speakers remain valid; only explicit source ambiguity notes create targeted review flags.
Classification and notes enter the same context/fingerprint in every mode.
Existing unversioned plans are accepted only when validating saved runs.
A compiler update may resume them when the complete logical requests and provider payloads still match; frozen plans and approvals are never migrated in place.
Accepted results are keyed by logical source/context rather than Japanese text alone.
Location hashes do not change their identity.
Explicit corrections retain history, require the current result hash, and invalidate affected review/injection/QA evidence.

Submission intent is durable before provider calls, and raw receipts are durable before acceptance.
A Live run saves its record after every paid call; a Batch collection saves it about once a second and at the end, since an interrupted collection rebuilds acceptance from the saved receipts and results and collects the same provider job again.
A worker rebuilds acceptance only on its first poll; it saved every later change itself, so a waiting Batch does not reread every saved result.
SDK-level paid retries are disabled.
For compiled agent plans, an uncertain submission blocks overlapping work; Guided fresh-run review follows the separate policy above.
Attaching a provider job still requires matching returned request IDs.
Approval receipts bind the project, immutable plan and quote with a profile-local signature.
Before approval, a quote whose settings only price its requests differently (see [Estimates and approval](#estimates-and-approval)) shows at the current prices with an approval token derived from them; approving with that token freezes the run's plan again with the current settings under the same run ID, since nothing has been sent or authorized, and a Batch runner counts each request's tokens for OpenAI's allowance when it packs them.
Any other settings change outdates the quote, and Progress's Estimate again repeats the organize or compile that made the run.
A saved boolean alone cannot authorize a worker.
Workers hold per-run locks and stop issuing work after losing their owning process.
Closing asks workers to stop at a checkpoint and a few seconds later ends any still running, with the processes they started.
An ended worker cannot clean up after itself, so each run worker keeps its temporary files, such as a restored game copy, in a [folder of its own](../backend/dazedtl/translation/jobs.py) that the app removes once it sees the worker gone, or at the next start.
A backend still busy 12 seconds after closing is ended with every process it started, workers in sessions of their own included, so a hung Git command cannot keep holding the game or its index; their runs read as interrupted on the next start, and approved Batch queues continue as after any interruption.
Closing or pausing cannot undo an already submitted provider request.

Git baselines and backup records gate new translation work.
Index writes wait up to ten seconds while another Git process holds the index lock, as any `git status` does while it refreshes the index, so status polls keep that refresh while workers write ([_run_git](../backend/dazedtl/engine/util/version_update/git_workflow.py)).
A checkout off the translation branch, or with an unfinished Git operation or asset sync, refuses every change to the game; [checkout_issue](../backend/dazedtl/translation/operations.py) names the problem for both the refusal and a translation warning that every Guided task shows.
Reviewed runtime manifests control patch scope; all .dazedtl work stays outside both branches.
DazedTL's own runtime files a game holds join every manifest that checkpoints, packages and QA records read ([dazedtl_files](../backend/dazedtl/engine/util/len_patch_scope.py)), and Guided proposes the same list: an assistant's manifest of data and `plugins.js` alone gave players a `plugins.js` loading a plugin the patch lacked, so the game stopped at boot.
Set up's files take the prepared game's copies as their originals, as `plugins.js` does; a game whose prepared backup lacks them, such as one set up after its Git baseline, gets them as translation-only additions instead of a checkpoint that fails.
[sync_patch_scope](../backend/dazedtl/engine/util/len_patch_scope.py) also refuses a `plugins.js` that switches on a plugin neither the patch nor the original game holds, so a plugin an assistant writes, or Guided's TL Inspector, which DazedTL leaves to the manifest, cannot reach players without its file.
The checkpoint passes the prepared backup's file list along with the restored originals because Git's ignored-asset inventory leaves out local-looking names such as a `Save…` plugin, and DazedTL's own plugins never count as the original game's because Git set up on a prepared game records them.
The MV/MZ writer retains source metadata on ordinary corrections.
The explicit rebase route proves its source matches a reviewed original-branch blob before rebuilding metadata for a new source version.
Official update operations reuse the existing preview hashes, conflict recovery and native-byte rules.
New originals are staged separately for engine preparation.
Staging lays the copy out as the game ([release_layout](../backend/dazedtl/engine/util/version_update/release_layout.py)): the release folder that lines up with the game's paths, compared case-insensitively, supplies the files, and a patch takes the game's spelling of each path it replaces.
A release holding fewer than half of the game's files is a patch, copied over the previous version so the files it leaves out stay; an MV/MZ patch gets the same data and plugin formatting as the game's own files, so it merges line by line.
The preview also reads the Japanese strings of the changed JSON files and plugins as lines ([text_changes](../backend/dazedtl/engine/util/version_update/text_changes.py)): releases line up by text, a translation by position, and the merged result says which translations survive, so the review counts what applying will really drop.
A plugin registry's settings read by plugin, and a plugin script's strings are its lines holding Japanese in quotes.
Applying cherry-picks the release, and a file Git cannot merge cleanly is resolved by [merged_file](../backend/dazedtl/engine/util/version_update/git_workflow.py)'s rules, which the preview and the line view follow too: prepared game data merges by value ([json_merge](../backend/dazedtl/engine/util/version_update/json_merge.py)), the plugin registry by plugin and value ([script_merge](../backend/dazedtl/engine/util/version_update/script_merge.py)), anything else by hunk with the release winning.
Formatted JSON repeats each command's lines, so Git can line a command the release inserted up against a translated one and conflict; by value, whatever the release left keeps its translation and source note, and whatever it changed comes from the release untranslated.
Plugin settings and plugin command arguments hold JSON inside strings, such as a whole quest list in one setting, so the merge by value reads those values too; otherwise a release that adds a quest returns every translated quest to Japanese.
`plugins.js` keeps each setting on one line, so Git conflicts wherever the release changes a translated setting, and the plugins the translation registered lost their registrations where the release registered its own; merged by plugin, they stay where they loaded, in the release's layout.
A translation that added or removed data the release also changed, such as a line wrapped onto two in a conversation the release edits, or a release file not in the prepared format, falls back to the hunk merge.
After a plugin script's hunk merge, each translated line the release left as it was goes back in, where the translation only rewrote text in quotes; code the translation rewrote stays as Git merged it.
The hunk merge lines files up with Git's histogram diff, as the cherry-pick's own merge does: the default diff stops searching after a few hundred changed lines and pairs formatted JSON's repeated lines with the wrong commands, so the release won conflicts it never had and replaced translations it left unchanged.
`git merge-file` takes the histogram diff from Git 2.44; an older Git keeps the default.
A local delivery packages only reviewed Git files.
Public publication remains a separate action.
Ace preparation runs in Python on every platform: `util/ace` ports RV2JSON 1.2.1 and RPGMakerDecrypter's archive reading instead of shipping their Windows executables.
The port writes RV2JSON's JSON and Ruby 3.4's Marshal bytes so games and existing `ace_json` exports read the same; it departs only where RV2JSON broke games or hid text: it finds data files in any case, keeps Change Vehicle BGM audio as objects, adds the equipment type names to `System.json` as `equipTypes` and packs translated map names into `MapInfos.rvdata2`, a Hash by map ID whose integer keys RV2JSON's update never matched.
[The Ace fixture](../tests/fixtures/ace/regenerate.py) records RV2JSON's own output for synthetic editor-shaped data, so conversion tests need neither Ruby nor real games.
RGSS3 reads only the archive while `Game.rgss3a` exists, scripts included, and probes on a real game confirmed it ignores loose copies and rejects an archive without its scripts.
So Set up keeps an encrypted game's archive in `.dazedtl/ace`, where releases and Git never see it, and patches carry it rebuilt with the game's current files; the rebuild keeps the original header, order and keys, so it reproduces an unchanged archive byte for byte.
Games also arrive with `ace_json` converted and the archive still beside Game.exe, from DazedMTLTool, which only told users to delete it, or from a manual RPGMakerDecrypter and RV2JSON conversion.
Convert Ace data is done only once no archive sits in the game root, which an opened project's state shows on every Guided task; it keeps existing `ace_json`, since converting again would overwrite its translations, writes only the exports it lacks ([actions](../backend/dazedtl/engine/util/ace/actions.py)) and sets the archive aside.
Until then packing refuses, and so do Apply and Release, which pack or check its receipt.
The game reads only Data, so every in-app write to `ace_json` packs it in the same step: Guided Apply, Text QA's apply and undo, Line widths fitting and History restores in the workflow worker, and Plugin files' apply and restore in its service ([pack_ace](../backend/dazedtl/compatibility/guided.py)).
A write that would reach a game still reading its archive refuses before anything is written; a pack that fails after the write reports that the game's data was not updated.
Packing saves a receipt bound to every current JSON input and its corresponding native output, and Set up's conversion saves the first one, since JSON just converted from Data holds what Data does.
From a current receipt a pack converts only the data files whose exports changed since.
Without one, such as for `ace_json` an earlier tool converted or Data an assistant wrote with its own tools, as Len's method does, a write packs only the exports it touched and leaves the rest of Data as it is.
Ace Release requires a current receipt, so `ace_json` edited or converted outside the app needs Pack outside edits, which packs everything and which Check and Release show only then.
The window caption comes from `Game.ini`'s Title, not the data, so packing writes the game title there as the editor does when it saves, and its receipt binds `Game.ini` with the data; older receipts count as outdated, so a game packed before this packs once more.
Game.exe reads that file with `GetPrivateProfileStringW`, which decodes a file without a byte order mark with the player's ANSI code page, and mkxp-z, which plays Ace games on Linux, the Steam Deck and Android (JoiPlay), [reads it as bytes](https://github.com/mkxp-z/mkxp-z/blob/dev/src/util/iniconfig.cpp), so in UTF-16 it finds no `Scripts=` and starts the game as RPG Maker XP.
Only ASCII reads alike in both, so the title is written in ASCII, accents and full-width forms taking their plain letters, letters such as Æ and ß their ASCII spellings and symbols such as ♥ left out, and only its line changes; a file already in UTF-16 keeps its encoding.
A title that would keep only a fragment in ASCII, such as a version number without the Japanese name beside it, leaves the old title in place.
Git holds no original of the converted JSON, so Event text sources reads a translated command's original text from the `_original` the engine keeps, and lists the converted `ace_json/scripts` as dependencies.
Ace data is translated by the MV/MZ engine, and an Ace project's runs set its `VXACE` option from the project's engine ([phase_workflow](../backend/dazedtl/engine/desktop/backend/workflow.py)), so the frozen plan and Batch runtime profile carry it.
With it, a translated text variable (code 122) is written as a Ruby double-quoted string, since Ace evaluates the operand with Ruby, where the template literal MV/MZ reads runs a shell command.
Earlier versions wrote Ace's as template literals, so packing writes each translated one, which keeps its `_original`, as the Ruby string holding the same text and leaves the JSON as it is ([ruby_text_variables](../backend/dazedtl/engine/util/ace/actions.py)); a literal that interpolates or holds a character code is left and logged, and receipts from before count as outdated, so those games pack once more.
Copied Names & glossary and Line widths tasks tell an Ace assistant where its data and scripts are and that the code-101 nameplate rules, slip check and layout check are MV/MZ only, since VX Ace's Show Text has no nameplate.
Guided checkpoint manifests derive translation-only additions from the registered original and saved source inventory, retaining previously tracked runtime assets when switching workflows.

## Windows

Each Windows rule lives where code cannot skip it, because the bugs it prevents never show on Linux.
Python touches files and starts processes through the [platform layer](../backend/dazedtl/system.py), whose docstring lists its rules; Ruff rejects the calls it replaces anywhere else, the engine included, and the Python tests fail on text opened without an encoding ([checks](development.md#checks)).
`held_open` makes a file look held by another reader, as Windows refuses to replace or delete one then, and a test drives each kind of writer through it.
[paths](../scripts/paths.mjs) rejects tracked names that differ only in case, which Windows finds as one file, and paths over the Windows length budget.
Code on a poll path starts no process: Defender makes each start slow, and one user's jobs froze for 17 seconds while every snapshot ran 22 Git commands.
A worker's parent on Windows is the virtual environment's launcher stub, so ownership checks use [launched_by](../backend/dazedtl/translation/ownership.py), never `os.getppid`.
[Shortcuts](../scripts/shortcuts.mjs) are written through IShellLinkW, since WScript.Shell passes their text through the ANSI code page.

## Backup storage

Both agent operations and UI checkpoints use translation/backups.py.
Each version-two snapshot is a complete path-to-content manifest with file sizes, permissions and empty directories; content-addressed objects are shared across original, prepared-source and workspace snapshots in the same game.
No delta chain or live-file hardlinks are used.
Snapshot identity covers file content, paths, modes and directories, so unchanged captures reuse a manifest.
Backup presentation checks manifest and payload availability instead of treating a profile reference as proof that its files still exist.
A poll checks shared object directories and payload sizes, and reuses that check while the snapshot's manifest and object folders keep their modification times ([record_status](../backend/dazedtl/translation/backups.py)).
Adding or removing an object changes its folder's time; a payload changed in place keeps those times, so only the full hash checks below notice it.
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
Each download, the launchers' Node included, is tried three times when the connection drops or the server is busy; a missing file or a wrong checksum stops at once.
Each step records its inputs in `.runtime/state.json` and reruns only when they change, so an update that changes a lockfile, a version file or the folder location repairs the install on the next start.
User installs omit the development tools; a Git checkout defaults to the development set.
npm comes from the pinned Node whenever it is installed, because the system Node may have none or a different version.
Translation projects are Git repositories, and Windows ships no Git, so setup installs Git for Windows' portable MinGit there, pinned in the same lock; other systems must provide `git`, and setup stops with the install command when they do not.
MinGit's system config sets `core.autocrlf=true` as a Git for Windows install does, which the engine's repo-local line-ending settings already override.
The launcher puts its Node and, on Windows, that Git first on the app's `PATH`, since the backend validates plugin scripts with `node` and runs `git`.
Detached launches log Electron's output to a temporary file and wait for its "shown" line, so the console stays open with the error when the app fails to start.
Shortcuts are written once per folder location, and a deleted desktop shortcut stays deleted.
A second install leaves them with the install they open while that one is still there and not older, and asks again on each start.
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
START.bat is one line, because cmd reads a batch file as it runs and the swap replaces it; that line ends with the launcher's result as an explicit exit code, since a bare `exit /b` would report success to `cmd /c` callers such as the live test.
Releases still keep `.node-version`, `.python-version` and the other files 2.0.0's launcher reads after its swap, since that launcher continues in place.
Files outside the manifest, such as `.venv`, `.runtime` and downloaded models, are never touched, and Git checkouts are left to Git.
"Restart to update" closes through the usual save handshake, refuses while a run is active, and relaunches through START with the app's switches, which waits for the old process to exit.
The backup also serves "Go back"; automatic checks skip the version the user went back from.
Settings > Updates shows the whole [changelog](../CHANGELOG.md), newest first and a few versions at a time, from the staged copy, which its manifest covers, or else from the install.
It leads with what's new: the versions after the installed one, after an update those since the version it replaced, or else the installed version's own entry.

Every tracked path stays within 185 characters, checked by [paths.mjs](../scripts/paths.mjs).
Windows Explorer and Python stop at 260 characters unless long paths are enabled, and Explorer unpacks a GitHub ZIP into a doubled top folder.
The budget leaves room for an install folder like `C:\Users\<26 characters>\Downloads\DazedTL-2.0.0\DazedTL-2.0.0\`.
The same check rejects paths, and module names without their import extension, that differ only in letter case.
Windows treats such names as one file, so an import of `./GuidanceReview` loaded `guidanceReview.ts` instead of `GuidanceReview.tsx` and broke the renderer build.
When a clash needs a rename, rename the file whose old copy would be harmless, because a ZIP unpacked over an older install keeps files the release dropped.
