# Frontend conventions

The default page design is the approved compact Settings layout: flat sections, aligned rows, small headings, and subtle dividers.
Overview and Settings are the reference implementations.
Keep engine and workflow decisions in the feature or backend that owns them.

## Ownership

| Directory | Responsibility |
| --- | --- |
| `app/src/app/` | Application shell, navigation, and shared state observation |
| `app/src/api/` | Public contracts, errors, transport, and named application operations |
| `app/src/state/` | Reusable action feedback, serialized drafts, and leave guards |
| `app/src/ui/` | Presentation components with no feature or backend imports |
| `app/src/styles/` | Design tokens, base elements, application layout, and shared component styles |
| `app/src/features/<name>/` | A feature's components, hooks, and styles |

Features may import the API, shared state, UI primitives, and `useApplication`.
Shared UI must not import features or call the backend.
The application shell composes feature screens; features should not import each other's internals.
Extract a shared component when two features need the same behavior or presentation.
Avoid creating a generic workflow engine or a schema-driven page builder in the UI.

## Page composition

Use `PageLayout` and `PageHeader` for the page frame, then compose `Section` components for related content.
Use `DetailRow` inside a description list for label/value summaries.
Use `FieldRow` for controls so the label, help text, and validation message stay associated with the input.
Pass the supplied control props to the actual input or select.

```tsx
<PageLayout variant="editor">
  <PageHeader title="Example" />
  <PageBody>
    <Section title="Preferences">
      <FieldRow id="example-name" label="Name" help="A name for this setup.">
        {(control) => (
          <input {...control} value={name} onChange={(event) => edit(event.target.value)} />
        )}
      </FieldRow>
    </Section>
  </PageBody>
  <ActionBar feedback={<Feedback dirty={dirty} pending={busy} />}>
    <Button disabled={busy} onClick={revert}>Revert</Button>
    <Button variant="primary" disabled={busy || !dirty} onClick={save}>Save</Button>
  </ActionBar>
</PageLayout>
```

Keep the editing footer outside `PageBody` so it cannot obscure fields.
Use `Tabs` and `TabPanel` when a page has distinct groups, with the same ID prefix and selected value for both components.
Overview keeps its project, status, next action, Quickstart, and recent projects together.
Use `Button` variants for primary, secondary, quiet, and destructive actions.
Use `Message` and `Feedback` for consistent loading, error, saved, and dirty states.
Use `Modal` for dialogs rather than adding another focus trap or dismissal handler.

## Styling

Start with `styles/tokens.css` for colors, typography, density, and spacing.
Shared component rules belong in `styles/ui.css`; shell rules belong in `styles/layout.css`.
Keep feature-specific selectors in the feature's stylesheet and import them through `styles/index.css`.
Prefer semantic tokens over new literal colors or repeated spacing values.
Reserve cards for content that benefits from a distinct container.
Review normal and compact window sizes when changing layout.

## Actions and drafts

Use `useAction` for an explicit operation's busy state, errors, and completion notice.
It prevents duplicate submissions and can refresh shared state after a completed action.
Do not retry writes automatically, especially operations that start paid work.

Use `useDraft` for recoverable edits and give it an identity that includes the owning project and document when applicable.
The underlying `DraftSession` serializes debounced draft writes, explicit commits, and flushes.
The feature supplies persistence, a content fingerprint, and reconciliation when edits can continue during a save.
Adopt the saved value and any recovered draft separately so dirty state remains accurate.
A persisted recovery draft is still unsaved until the user commits it.
Settings and Guided context documents use this lifecycle through their feature hooks.
Do not store credentials in drafts.

Navigation calls `flushDrafts` before leaving a page or switching projects.
The application provider also registers one native close handler for these guards.
Close attempts are identified individually so a delayed response from an earlier attempt cannot close a later one.
Features should register additional leave guards only for state that the shared draft session cannot own, such as an unsaved credential dialog.

## Shared application state and API changes

Read application and job state through `useApplication`.
`ApplicationStore` owns the single polling loop while work is running and coalesces refreshes.
Feature components must not add polling timers or fetch competing copies of the application snapshot.
Feature-local reads, such as opening Settings, can still use the API client.

Add named operations to `api/client.ts` instead of calling the preload RPC interface from components.
Define request and response types in `api/contracts.ts` and map backend records in `backend/dazedtl/api/views.py`.
Keep legacy field names and records inside the backend adapter or view projection.
When adding a method, update `backend/dazedtl/api/protocol.json`, the typed contract, the named client operation, and the Python handler together.
Set `refresh` when the mutation changes shared application or workflow state.
Allow `duringClose` only for operations needed to finish saving or reading during shutdown.
Bump the protocol version when existing clients can no longer use a changed request or response contract.
The protocol validates the envelope and version; TypeScript types are not runtime validation for arbitrary response payloads.
