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
Guided Workflow owns preparation through results; Len's Method will retain its own skills and progress model.

## UI and state decisions

Use the flat, compact [Settings](../app/src/features/settings/Settings.tsx) and [Overview](../app/src/features/overview/Overview.tsx) implementations as page examples.
Compose shared UI primitives with design tokens; editing footers sit outside scrolling content, and Overview keeps project/status/actions together.
Reserve cards for content requiring a distinct container.

Project identity, translation method, and visible screen are separate so navigation cannot change a project's workflow.
`useApplication` supplies shared state through one observer; feature polling loops would introduce competing reads.
`useAction` guards duplicate submissions, while `useDraft` serializes recovery writes and explicit saves.
Recovery drafts remain dirty until committed; leave guards flush them before navigation and close.
Never retry writes automatically, since some actions submit paid work.

Project-format changes increment `SCHEMA_VERSION` and register consecutive upgrades in [projects/store.py](../backend/dazedtl/projects/store.py).
The storage helper validates the result, retains the original bytes in a backup, and replaces the file atomically; unsupported or invalid formats are left untouched.
Engine-owned settings and run formats remain the adapter's responsibility.
Diagnostics record only fixed metadata and relative code locations, excluding exception messages, payloads, and raw stderr.

## API changes

Add renderer operations through [client.ts](../app/src/api/client.ts), with request/response types in [contracts.ts](../app/src/api/contracts.ts).
Update the shared [protocol manifest](../backend/dazedtl/api/protocol.json), Python handler, and [public views](../backend/dazedtl/api/views.py) together; legacy records stay behind the view boundary.
Bump the protocol version for incompatible contracts so stale clients are rejected before mutations execute.
The manifest declares state-refresh and close-time permissions; permit close-time operations only when required to finish saving or reading.
Envelope/version checks and TypeScript types do not validate arbitrary payloads; domain operations remain responsible for input validation and ownership checks.
