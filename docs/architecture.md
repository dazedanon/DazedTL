# Architecture

## Ownership

| Location | Responsibility |
| --- | --- |
| [app/src/app](../app/src/app) | Shell, navigation, and the single application/job observer |
| [app/src/features](../app/src/features) | Each feature's components, hooks, and styles |
| [app/src/ui](../app/src/ui), [styles](../app/src/styles) | Shared presentation, design tokens, and layout |
| [app/src/state](../app/src/state) | Action feedback, serialized drafts, and leave guards |
| [app/src/api](../app/src/api) | Typed contracts, transport, and named application operations |
| [app/electron](../app/electron) | Native dialogs, approved folder opening, close handshake, and Python process |
| [backend/dazedtl](../backend/dazedtl) | Project identity, settings, workflow actions, and run ownership |
| [compatibility](../backend/dazedtl/compatibility) | The only boundary allowed to import DazedMTLTool code |

The shell composes features; features use shared services without importing each other's internals.
Shared UI components do not import features or call the backend.
The renderer is sandboxed and has no direct filesystem, process, or network access.
The adapter retains existing engine behavior while capabilities are extracted incrementally.
The Qt GUI in the sibling `DazedMTLTool` checkout is the reference for guided workflow
ordering and behavior. The separate frozen `DazedMTLTool-engine` checkout supplies runtime
compatibility code only; its retired Electron interface is not a UX reference.
The default engine location is shared by the launcher and Electron backend through
[engine-source.cjs](../app/electron/engine-source.cjs); see README for snapshot recovery.
The Translation service owns project operations, request plans, accepted results, and run recovery for both the UI and the external agent helper.
Len's maintained skills own engine investigation and methodology; the compatibility layer supplies the existing context, Git, preparation, injection, and provider helpers.
Existing phased jobs retain their original engine-owned records and recovery path rather than being rewritten into a different request format.
The Translation workspace composes file selection, preferences and the preserved phased runner.
Their controller exposes specific engine actions through one-use, project-bound previews; source,
selection, settings and runtime-scope changes invalidate the relevant preview. The preserved runner
continues to own parsing, speaker preparation, phase profiles, glossary collection and Batch receipts.
App workers own source backup, Git baselines, checkpoints and local patch packaging for both approaches.
Guided release freezes the current runtime scope and original-source bindings through an app-only,
one-use preview. Patch packaging saves its checkpoint and workspace restore point as part of the
same operation. Clean game packaging reuses the Qt packager through the compatibility worker,
verifies the source inventory and destination, and publishes a verified archive atomically.
Neither operation manufactures a user-review record or completes Len's report-based QA.
The project helper cannot invoke Guided packaging; its separate QA requirements remain in force.
Legacy Guided review receipts remain readable for existing records.

## UI and state decisions

### UX principles

Strive for [Nielsen's ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/)
when designing and reviewing this tool. Make current state and the next useful action visible;
use translation tasks and familiar language; offer clear exits and recovery; keep shared controls
consistent; prevent scope and spending mistakes; make prerequisites visible instead of requiring
memory; support both guided and experienced use; prioritize relevant actions; give errors a
practical recovery path; and put concise help beside the task that needs it. Use these principles
to evaluate real workflows, rather than adding extra panels or confirmation steps to satisfy a checklist.

### Workflow and shared presentation

Use the flat, compact [Settings](../app/src/features/settings/Settings.tsx) and [Overview](../app/src/features/overview/Overview.tsx) implementations as page examples.
Compose shared UI primitives with design tokens; editing footers sit outside scrolling content, and Overview keeps project/status/actions together.
Reserve cards for content requiring a distinct container.
Use the shared [JobStatus](../app/src/ui/JobStatus.tsx) for operation summaries, including Overview,
so generic completion messages are handled consistently while useful detail remains visible.
Action controls pair the shared pending button and status feedback with `useAction`'s guarded action key.
Saved operation indexes carry their action identity so feedback can remain beside the correct control after navigation or restart.
Repeated label/action rows use [ActionList and ActionRow](../app/src/ui/ActionList.tsx): one shared
action-column width, token-based gaps, wrapping text, and a stacked layout based on available
container width. Rows grow with feedback rather than fixing heights or clipping content.
Staged preparation requires existing game JSON at preview and execution; missing Ace exports cannot count as completed formatting or authorize a new baseline.
Formatting, GameUpdate creation, initial source backup, and local estimation consume a preview immediately after the user's click;
the same backup, project ownership, input validation, and one-use execution checks still apply.
Replacement backups, paid work, runtime replacement, and source refresh retain their review requirements.

Translation follows the working Qt GUI's task dependencies through the tasks in
[workflow.ts](../app/src/features/guided/workflow.ts). The app sidebar stays global; the local
task rail becomes a stage strip when the workspace is narrow. One task occupies the editing
body and its action footer stays outside the scroll region. One copied setup task identifies
speaker formats, runs local name collection, then uses those results for the glossary/context
investigation. Guidance review and layout settings follow before
the named database, dialogue and variable-cache actions. The comparison cache is distinct from
auditing optional variable assignments, scripts and plugin commands. Advanced text starts with
that audit and keeps each dependent range/filter beside its source; a phase with no enabled
sources is skipped, and code 122 requires explicit audited IDs rather than a legacy fallback.
New guided projects clear inherited advanced targets; existing projects and frozen runs retain
their choices. Applying and testing a small scope is available before expanding translation.
Speaker findings use the structured contract generated by
[speaker_setup.py](../backend/dazedtl/translation/speaker_setup.py). A copied setup task binds its
report to this project and request. The app verifies source hashes before enabling only confirmed,
high-confidence rules; prose reports and partial, stale or foreign findings cannot configure options.
The agent's scoped `speakers --scan` helper applies the rules and launches the preserved parser's
scan phase in an isolated worker without credentials or network access. It never translates
names; literal nameplates and the native actor/variable lookup tables feed the rest of the setup
investigation. Preferences and the consumed report are saved atomically through the compatibility
boundary. Pending option drafts and actively running workers defer application; dormant API runs
do not block speaker setup or local scanning and retain their frozen settings and receipts.
The shared observer reports scanner results; manual overrides survive new findings
until explicitly reset.
Names and context completion requires a request-bound context report, a current local name scan, and matching saved document revisions.
Document existence alone does not verify an investigation; existing guidance can be reviewed independently.
One review task keeps glossary, translation style/quirks and game context in separate tabs, with custom guidance available separately.
The selected tab is retained per project, and legacy glossary/voice review positions open the corresponding tab.
Missing custom files remain addressable while their recovery drafts exist.
Switching tabs retains edits without completing review; continuing validates the complete set and reports successful writes if a later document save fails.
Empty guidance requires an explicit retained choice, and disk changes beneath a draft require comparison before a guarded replacement or rebase.
The shared plain-text editor retains glossary category headers, source (translation) entries and same-line notes; engine parsing and per-batch selection remain unchanged.
Layout recommendations reuse the first investigation’s source evidence; defaults are identified separately and remeasurement remains optional.
Saved findings describe the investigated source; translating runtime files does not erase that record.
New projects also clear inherited optional speaker rules.
Prepare retains the untouched backup, one stoppable file-preparation action, and a reviewed version baseline as separate tasks.
The preparation worker records each completed stage against the current prepared files, stops on failure or cancellation, and resumes remaining stages without repeating current completed work.
Individual preparation tools update the same receipts; GameUpdate file installation does not imply a tested delivery configuration.
New baselines require current preparation evidence at preview and execution; existing Git baselines remain usable without historical preparation receipts.
The explicit untranslated/original-source choice and version are retained in the Guided form.
Saving a reviewed baseline continues to speaker/context setup only after the saved operation and baseline are confirmed, without starting an assistant task.
Recovery and official-version updates are project utilities, outside the normal preparation sequence.
Their primary actions use the shared [ActionSlot](../app/src/ui/ActionSlot.tsx) to stay in the host dialog's footer while content scrolls.
The update view shows one current preparation/comparison at a time; a later attempt or changed Git
state prevents an old comparison from being offered for application. Backup history is grouped by
game versus project files and appears only after the user chooses recovery.
Navigation never completes a task. Prepared originals are summarized; recent activity holds saved history, while active work and required
approval remain visible across areas. Assistant task controls describe the expected return and
report only copied instructions or saved findings, never an external process inferred from a click.
Output availability, application to runtime files, assistant QA findings, and package availability
are separate observations. Execution rechecks source, scope, destination, and ownership evidence.
Application receipts distinguish later fitting or QA edits from new outputs that have not been
applied. Release plans bind the profile's working-source index and original blobs;
refreshing or expanding a source pass invalidates pending package plans without rewriting old runs.

The selected phase files bind each new run and each application preview. Working copies are
prepared automatically without removing other phase work. The compatibility launcher filters
the preserved phase's selected files, retaining its profiles, glossary, speakers, and frozen run format.
New tracked inputs come from original-branch blobs. Ace exports bind to their native original blobs
when available, so fitting or packing runtime translations does not create false source drift;
untracked exports bind to source bytes.
Source changes block new work until an explicit refresh archives affected working copies, outputs,
and variable cache in profile source-history. Existing runs keep their original recovery records.
Runs retired by that refresh cannot merge older results into the new pass; their frozen outputs
remain inspectable and exportable under the original project owner.
The former manual screen remains a compatibility route into Translation, preserving saved project identity.

Project identity, execution mode, and visible screen are separate. Registry upgrades retain existing IDs,
backend job references, phase selections and recovery data when adding workflow screens.
Portable workflow options live in the selected game's .dazedtl/len-method/workflow.json; the old Len project.json is imported without being overwritten.
The app profile holds connections, recoverable drafts, run plans and receipts, and older full-copy backups. New source/workspace snapshots live in the game's .dazedtl/backups/v2 store. Source guidance remains in the established game files.
`useApplication` supplies shared state through one observer; feature polling loops would introduce competing reads.
The application provider supplies its API and browser event subscriptions; the observer owns response ordering and refresh scheduling.
An open project stays observable while no app worker is active so external assistant reports become visible. Saved run indexes keep these observations small; full request bodies are checked at execution/inspection boundaries.
Backend disconnection invalidates pending reads so a late response cannot restore an obsolete connected state.
`useAction` guards duplicate submissions, while `useDraft` serializes recovery writes and explicit saves.
Recovery drafts remain dirty until committed; leave guards flush them before navigation and close.
Guided engine options use the same draft session and retain the native revision check. Its step and
setup-form recovery live alongside project records in the profile.
Opening Guided transfers any pending shared-context draft before linking the native workflow.
Never retry writes automatically, since some actions submit paid work.

Project-format changes increment `SCHEMA_VERSION` and register consecutive upgrades in [projects/store.py](../backend/dazedtl/projects/store.py).
The storage helper validates the result, retains the original bytes in a backup, and replaces the file atomically; unsupported or invalid formats are left untouched.
Project opening, selection, and navigation publish their in-memory state only after persistence succeeds.
Engine-owned settings and run formats remain the adapter's responsibility.
Diagnostics record only fixed metadata and relative code locations, excluding exception messages, payloads, and raw stderr.

Connections and preferences share one atomic record in workspace `settings/settings.json`.
Saved secrets never enter renderer responses or recovery drafts, and model drafts are bound to connection IDs.
The public preference schema contains language, model, and per-model request/pricing options; legacy formatting and other engine values are retained privately through a backed-up versioned upgrade.
The adapter materializes legacy settings only before engine actions and checks the original provider route before resuming saved runs.
Connection checks are explicit model-list requests, with bounded reads, no redirects, and no generated text.
The compatibility pricing resolver runs without credentials, reuses the preserved pricing rules, and labels cached catalog versus built-in rates.
New manual plans freeze resolved request size and base rates before hashing; small worker wrappers apply this policy before the native engine imports, including per-file workers.
Existing plans without a policy retain their original behavior; provider cache and batch adjustments remain in the engine.

## API changes

Add renderer operations through [client.ts](../app/src/api/client.ts), with request/response types in [contracts.ts](../app/src/api/contracts.ts).
Update the shared [protocol manifest](../backend/dazedtl/api/protocol.json), Python handler, and [public views](../backend/dazedtl/api/views.py) together; legacy records stay behind the view boundary.
Bump the protocol version for incompatible contracts so stale clients are rejected before mutations execute.
The manifest declares state-refresh and close-time permissions; permit close-time operations only when required to finish saving or reading.
Envelope/version checks and TypeScript types do not validate arbitrary payloads; domain operations remain responsible for input validation and ownership checks.

## Translation execution and the agent boundary

The generated starting prompt uses scripts/project.py against an authenticated loopback endpoint in the running backend.
The connection descriptor is local to the profile, permission-restricted, and removed on shutdown. Its token is never embedded in a handoff.
Agent operations use the same locked dispatch and project/run ownership checks as Electron; the helper has no settings or general shell endpoint.
The app controls its workers. External assistant activity is reported from saved artifacts and must not be represented as an app-owned process.

A compiled plan freezes sources, full context, field constraints, provider parameters, rates, and connection identity.
Tracked game-source dependencies bind to their original-branch blobs; untracked source exports, project guidance and the plan file bind to their exact bytes.
Both API transports consume the same logical request builder. Request IDs, speaker/scene context and protected tokens survive adapter conversion.
Version-two source plans require per-line text types and explicit nullable speakers. Unknown speakers remain valid;
only explicit source ambiguity notes create targeted review flags. Classification and notes enter the same context/fingerprint in every mode.
Existing unversioned plans are accepted only when validating saved runs. A compiler update may resume them when
the complete logical requests and provider payloads still match; frozen plans and approvals are never migrated in place.
Accepted results are keyed by logical source/context rather than Japanese text alone. Location hashes do not change their identity.
Explicit corrections retain history, require the current result hash, and invalidate affected review/injection/QA evidence.

Submission intent is durable before provider calls, and raw receipts are durable before acceptance. SDK-level paid retries are disabled.
An uncertain submission blocks overlapping work; attaching a provider job still requires matching returned request IDs.
Approval receipts bind the project, immutable plan and quote with a profile-local signature. A saved boolean alone cannot authorize a worker.
Workers hold per-run locks and stop issuing work after losing their owning process. Closing or pausing cannot undo an already submitted provider request.

Git baselines and backup records gate new translation work. Reviewed runtime manifests control patch scope; all .dazedtl work stays outside both branches.
The MV/MZ writer retains source metadata on ordinary corrections. The explicit rebase route proves its source matches a reviewed original-branch blob before rebuilding metadata for a new source version.
Official update operations reuse the existing preview hashes, conflict recovery and native-byte rules. New originals are staged separately for engine preparation.
A local delivery packages only reviewed Git files. Public publication remains a separate action.
Guided rewrap application also requires a matching completed scan. Ace's conversion workers stage
bundled executables and the Wine prefix in the profile. Guided checkpoint manifests derive
translation-only additions from the registered original and saved source inventory, retaining
previously tracked runtime assets when switching workflows.

## Backup storage

Both agent operations and UI checkpoints use translation/backups.py. Each version-two snapshot is a complete
path-to-content manifest with file sizes, permissions and empty directories; content-addressed objects are shared
across original, prepared-source and workspace snapshots in the same game. No delta chain or live-file hardlinks
are used. Snapshot identity covers file content, paths, modes and directories, so unchanged captures reuse a manifest.
Backup presentation checks manifest and payload availability instead of treating a profile reference as proof
that its files still exist. Resolved locations are shown in the UI; Electron opens only backup folders returned
as available by the backend. Full content hashes are still verified at restore and reuse boundaries.
The managed store has its own writer lock. Content is verified before reuse/publication; source mutations abort
capture. A failed capture removes only unpublished objects it created. Existing snapshots are never pruned.
After a source backup is successfully saved, the operation reconciles profile references to a deleted
workspace snapshot and engine investigation whose evidence files are all missing. It archives those
records under profile `backups/stale-project-records` before retiring them. Read-only observations do
not clear records. Existing or unreadable artifacts, prepared-original baselines, and run history stay
intact; a failed or cancelled backup does not retire anything.

Workspace capture excludes the entire .dazedtl/backups directory, including any pre-existing manual backups.
Source capture excludes .git and .dazedtl. Arbitrary nested destinations remain forbidden. The v2 subdirectory
avoids repurposing existing backup folders. Older version-one full-copy snapshots remain supported by the reader.
Engine operations obtain temporary verified normal files through materialized; patch checkpoints materialize
only their runtime source paths. No expanded cache is retained. Restore verifies into a staging directory before
publishing a new destination, refuses existing or overlapping targets, and reconstructs empty directories and file modes.
The independent scripts/backups.py reader can recover a moved game without its former app profile. Restoring a
workspace does not transplant connections, paid-job ownership or spending authorizations from another app profile.
