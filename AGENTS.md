# DazedTL migration agreements

- Improve the existing translation behavior; preserve the RPG Maker and WOLF parsers and context rules.
- Guided Workflow and Len's Method are the primary translation methods.
- Project identity, selected translation method, and visible screen are separate state.
- Use the compact Settings design as the default for most pages: flat sections, small headings, aligned rows, and subtle dividers.
- Compose new pages from `app/src/ui/` and use tokens from `app/src/styles/tokens.css`; see `docs/frontend.md` for conventions.
- Keep feature components, hooks, and styles in their own `app/src/features/` directory.
- Use `useAction` for action feedback and `useDraft` for recoverable edits; do not introduce page-specific save queues or close handlers.
- Read shared application and job state through `useApplication`; do not add feature polling loops.
- Keep RPC calls in `app/src/api/client.ts` and public contracts in `app/src/api/contracts.ts`; update the shared protocol manifest and Python views together.
- Keep Overview's project, status, next action, Quickstart, and recent projects visible together instead of adding cards or unnecessary tabs.
- Reserve cards for content that needs a distinct container; avoid large padded or decorative boxes around routine forms and summaries.
- Keep primary actions easy to find; editing pages need a footer outside the scrolling content so Save/Revert never cover fields.
- Only `backend/dazedtl/compatibility/` may import code from DazedMTLTool during migration.
- Keep credentials, run files, logs, caches, and user projects outside this repository.
- Add functional pages one at a time; do not add prototype translation routes or synthetic output to the product UI.
- The user has asked us not to run tests while the Electron architecture and UX are being revised.
- Builds and visual review are appropriate; do not run test suites or create test substitutes unless the user requests them.
- Preserve the sibling DazedMTLTool repository and its uncommitted work.
