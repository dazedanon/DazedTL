# Architecture

## Page layout

The compact Settings design is the default for most pages.
Use flat sections, small headings, aligned labels and values, and thin dividers to separate related information.
The shared `PageLayout`, `PageHeader`, `Section`, and `DetailRow` components establish this pattern for summary pages.
Editing pages also use `PageBody`, `FieldRow`, `Tabs`, and `ActionBar`.
See [Frontend conventions](frontend.md) for ownership, composition, and state lifecycles.
Use tabs for distinct groups of settings, while keeping Overview's project, status, next action, Quickstart, and recent projects visible together.
Cards are reserved for content that benefits from a distinct container.
Routine forms and summaries should not gain large padded boxes or decorative empty states.
Place Save/Revert in a separate footer on editing pages so the controls cannot cover the form.
Use readable text and compact spacing, with sensible wrapping in smaller windows.

## Project identity

A project is a game folder, detected engine, and chosen translation method.
Its ID stays stable when the user changes pages.
The current screen is stored separately from the method, so opening Settings cannot turn a Guided Workflow project into another kind of project.

The first migrated UI exposes the guided RPG Maker MV/MZ path.
The project model also names Len's Method explicitly, ready for that migration without conflating it with an engine or a screen.

## Application boundary

Electron owns native folder dialogs, approved folder opening, application lifecycle, and the Python process.
The sandboxed renderer has an allowlisted preload interface and no direct filesystem, process, or network access.
The Python API owns project state, settings, workflow actions, and run ownership.
`backend/dazedtl/api/views.py` projects legacy records into explicit application views before sending them to the renderer.
`app/src/api/contracts.ts` defines the public views and each method's request and response types.
`backend/dazedtl/api/protocol.json` is the shared version and method manifest used by Python, Electron, and the renderer.
Requests carry the protocol version, so an incompatible client is rejected before executing a mutation.
Replies carry a version and structured error code as well.
The manifest declares which mutations refresh shared state and which operations can finish during close.
TypeScript compilation checks that the client contract and manifest have the same method names.
Python checks that every manifest method has an application handler at startup.

`ApplicationProvider` owns one `ApplicationStore` for the window.
It reads an application snapshot and the active Guided view together, serializes refreshes, and observes active jobs from one polling loop.
Mutation events invalidate older reads before they can replace newer state.
Polling stops when the app is idle or a read fails, and writes are never automatically retried.
Settings and context editors use the same serialized draft lifecycle, with feature-specific persistence and reconciliation.
Navigation flushes recoverable drafts before changing pages or projects, and the native close handshake flushes registered guards before exit.

Each application instance owns an isolated profile and workspace.
Credentials never enter renderer responses, and saved runs remain owned by their original project and frozen plan.

## Existing translation behavior

Only `backend/dazedtl/compatibility/` imports from the previous repository.
The adapter reuses `ManualJobs`, `Workflows`, `Operations`, `SettingsStore`, and the shared game detector.
The rest of the new backend speaks to the adapter through application-level operations.

`Workflows.phase` still chooses the original RPG Maker phase profiles and prepares the engine's context.
The existing worker still executes `modules/rpgmakermvmz.py` and its parsing, speaker, glossary, wrapping, and provider behavior.
Batch submission and unresolved-speaker approvals remain explicit parts of the run.

The renderer keeps file preparation, context, execution, progress, and results inside Guided Workflow.
There is no separate generic Translation tab controlling a guided phase.
There is no synthetic translation route in the product UI.

## Incremental extraction

Move a capability and its required resources into the new backend when its boundaries are understood.
Replace the corresponding adapter calls as that happens.
Keep engine-specific logic in its engine module instead of reducing it to generic text extraction.

Len's Method retains its own skills, assistant handoffs, and progress model.
It will use the shared project identity and explicitly selected DazedTL services when migrated.
