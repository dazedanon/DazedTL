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
The Translation service owns project operations, request plans, accepted results, and run recovery for both the UI and the external agent helper.
Len's maintained skills own engine investigation and methodology; the compatibility layer supplies the existing context, Git, preparation, injection, and provider helpers.
Existing phased jobs retain their original engine-owned records and recovery path rather than being rewritten into a different request format.
Guided Workflow and Translate files compose the same file selection, preferences and phased runner.
Their controller exposes specific engine actions through one-use, project-bound previews; source,
selection, settings and runtime-scope changes invalidate the relevant preview. The preserved runner
continues to own parsing, speaker preparation, phase profiles, glossary collection and Batch receipts.
App workers own source backup, Git baselines, checkpoints and local patch packaging for both approaches.
Guided review records the user's attestation against current runtime files (and Ace's JSON inputs),
separately from Len's report-based QA evidence. Neither workflow's review completes the other's QA.
The project helper cannot create a Guided user-review attestation or invoke Guided packaging;
those operations are reachable only through the app's consumed Guided preview.

## UI and state decisions

Use the flat, compact [Settings](../app/src/features/settings/Settings.tsx) and [Overview](../app/src/features/overview/Overview.tsx) implementations as page examples.
Compose shared UI primitives with design tokens; editing footers sit outside scrolling content, and Overview keeps project/status/actions together.
Reserve cards for content requiring a distinct container.
Use the shared [JobStatus](../app/src/ui/JobStatus.tsx) for operation summaries, including Overview,
so generic completion messages are handled consistently while useful detail remains visible.
Action controls pair the shared pending button and status feedback with `useAction`'s guarded action key.
Saved operation indexes carry their action identity so feedback can remain beside the correct control after navigation or restart.

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
setup-form recovery live alongside project records in the profile; navigation never starts an action.
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

Workspace capture excludes the entire .dazedtl/backups directory, including any pre-existing manual backups.
Source capture excludes .git and .dazedtl. Arbitrary nested destinations remain forbidden. The v2 subdirectory
avoids repurposing existing backup folders. Older version-one full-copy snapshots remain supported by the reader.
Engine operations obtain temporary verified normal files through materialized; patch checkpoints materialize
only their runtime source paths. No expanded cache is retained. Restore verifies into a staging directory before
publishing a new destination, refuses existing or overlapping targets, and reconstructs empty directories and file modes.
The independent scripts/backups.py reader can recover a moved game without its former app profile. Restoring a
workspace does not transplant connections, paid-job ownership or spending authorizations from another app profile.
