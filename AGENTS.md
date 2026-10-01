# Repository agreements

## Changes

- Preserve existing user changes and the sibling DazedMTLTool repository.
- Keep changes focused; preserve engine parsing, context, and translation behavior during migration.
- Follow the ownership boundaries in [architecture](docs/architecture.md) and reuse its shared UI and state mechanisms.
- Add functional pages incrementally; keep prototype translation routes and synthetic output out of the product.
- Keep credentials, games, run files, logs, and caches outside the source tree.
- Use `rg` for repository searches.
- For project-helper connection failures, follow the [sandboxed connection guidance](docs/translation-contract.md#sandboxed-connections).

## Documentation

- Keep README for setup and current limitations, architecture for boundaries and decision rationale, and AGENTS for working rules.
- Keep each fact in one place; link to authoritative code or documentation instead of copying it.
- Update affected documentation in the same change; remove obsolete guidance.
- Add a document only for a distinct reader need that existing documentation cannot serve concisely.
- Prefer working code examples over copied snippets; avoid feature inventories, function catalogs, and progress diaries.
- Keep `docs/migration.md` as historical reference, not a second source of current status.

## Testing

- Automated testing is enabled. Run node scripts/test.mjs for foundation or shared behavior changes; use focused targets while iterating.
- Builds, static checks, and visual review are allowed when relevant to the change.
- During visual review, check text-to-action spacing and redundant status text at normal and minimum window sizes, including wrapped descriptions and completed-job messages.
- Action buttons must acknowledge pending work and show success or failure near the control; check saved artifacts on disk before presenting them as available.
- Before adding a test, name the concrete failure it protects against and search for overlapping coverage.
- Extend an existing case for a distinct risk when readable; use the cheapest level that reliably catches the failure.
- Reserve application tests for a few critical user journeys; use direct tests for difficult parsing, reconciliation, and other isolated logic.
- Skip tests for trivial wrappers, constants, exact wording, incidental CSS, source substrings, framework guarantees, and duplicated behavior.
- Keep tests hermetic with small generated or committed fixtures; no real providers, user games, credentials, or local workspace dependencies.
- The full test suite has a hard 10-second wall-clock budget, including runner startup, fixtures, and teardown; builds and dependency installation are separate.
- Measure the full suite before adding or expanding tests; at 10 seconds or more, pause additions and ask the user to choose removing redundant tests, refactoring for speed, or increasing the limit.
- If added coverage reaches the limit, report the overrun and present the same choices before proceeding with more tests.
- Do not bypass the budget by silently deleting or skipping tests, splitting suites, weakening checks, or raising the limit.
- Do not optimize for test counts or coverage percentages; report checks run, relevant runtime results, and unverified behavior.

## Foundation behaviors to protect

- Draft edits survive navigation, save/close races, and recovery.
- Project and run ownership remain correct through switching, interruption, and resume.
- File operations preserve source games and reject invalid destinations; credentials remain isolated from renderer responses and drafts.
- Paid work requires the intended approval and cannot be submitted twice by repeated input or retries.
- Engine changes preserve control codes, speakers, glossary/context rules, and output formatting.
