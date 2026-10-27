# Repository agreements

## Changes

- Preserve existing user changes and the sibling DazedMTLTool repository.
- Work on the `dev` branch; `main` changes only through `node scripts/release.mjs`.
- Land one feature or fix at a time: merge it into `dev` and verify it there before starting the next.
  Run sessions in parallel only for areas that share no files, and never collect several feature branches to merge together at release time.
- Put problems you notice outside the task under New in the bug list (`~/DazedTranslations/DazedTL-bugs.md`) instead of fixing them; the `dazedtl-triage` skill works through it.
- Run every session and subagent you start or propose on Opus 5.5 (`claude-opus-5-5`, Agent model `opus`), never Sonnet or Haiku, and pass its effort explicitly: `xhigh` for the queue coordinator and the hardest calls, such as a rule already patched several times or a fix that did not hold; `high` for design, reworks, hard debugging and triage; `medium` for known one-area fixes, reviews, probes, merges, pushes and mechanical edits; never `low`.
  A session that starts others runs at the highest effort it hands out, since `start_session` cannot start one above its starter's.
- Before fixing a bug, read the git history of the code involved.
  If the same behavior was fixed before, stop and report the root cause with a proposed rework instead of patching it again.
- Give each rule one definition, such as how a text block's rows are grouped or how a file's status is counted, and call it from every place that needs it.
  When a fix touches a rule that is defined in more than one place, merge the copies first, or report them if merging is large.
- Follow the ownership boundaries in [architecture](docs/architecture.md) and reuse its shared UI and state mechanisms.
- For screens, action handlers or observed state, follow the [UX principles](docs/architecture.md#ux-principles), [visual design](docs/architecture.md#visual-design), [workflow and shared presentation](docs/architecture.md#workflow-and-shared-presentation) and [navigation and responsiveness](docs/architecture.md#navigation-and-responsiveness) sections, including their review steps.
- Keep credentials, games, run files, logs, and caches outside the source tree.
- Key saved work on its inputs and an explicit version, never on hashes of source files; see [persistence](docs/architecture.md#persistence-and-settings).
- For project-helper connection failures, follow the [sandboxed connection guidance](docs/translation-contract.md#sandboxed-connections).

## Documentation

- Keep each fact in one place and link to the authoritative code or document instead of copying it; the [documentation list](docs/development.md#documentation) says what each document holds.
- Update affected documentation in the same change and remove obsolete guidance.
  Add a document only for a reader need no existing one serves, and write no feature inventories, function catalogs or progress diaries.
- Add a rule to this file only when most sessions need it and no script can enforce it; otherwise enforce it in a script, or put it in the document or skill where it applies.

## Testing

- Run `node scripts/test.mjs` for foundation or shared behavior changes, and `node scripts/build.mjs` for any code change; it runs the formatting, lint and type checks.
  [Checks](docs/development.md#checks) lists what each covers, focused test commands, and the formatter.
- Run the [live test](docs/development.md#live-test) for changes to setup, launching, updates, file or process handling, or other platform-specific behavior; CI runs it on Windows and Linux.
- Test every new feature end to end on Linux, as a user would, before reporting it done.
- Reproduce bugs and test features end to end from a [test scenario](docs/development.md#test-scenarios).
  When none fits, add a scenario, game variant or stand-in mode there instead of building a private kit of games, profiles, providers or drivers.
- Turn each bug's reproduction into a test that fails without the fix and commit it with the fix, unless the bug is a kind the skip rule below lists.
- Give each new test a concrete failure it catches, at the cheapest level that catches it reliably: extend an overlapping case when it stays readable, keep application tests to a few critical journeys, and test parsing, reconciliation and other isolated logic directly.
- Skip tests for trivial wrappers, constants, exact wording, incidental CSS, source substrings, framework guarantees, and duplicated behavior; keep tests hermetic, with no real providers, user games, credentials, or local workspace.
- If `node scripts/test.mjs` reports its [budget](docs/development.md#checks) exceeded, stop adding tests and ask the user to choose between removing redundant tests, making them faster or raising the limit; never delete, skip, split or weaken tests to get under it.
- Do not optimize for test counts or coverage percentages; report checks run, relevant runtime results, and unverified behavior.

## Foundation behaviors to protect

- Draft edits survive navigation, save/close races, and recovery.
- Project and run ownership remain correct through switching, interruption, and resume.
- File operations preserve source games and reject invalid destinations; credentials remain isolated from renderer responses and drafts.
- Paid work requires the intended approval and cannot be submitted twice by repeated input or retries.
- Engine changes preserve parsing, control codes, speakers, glossary/context rules, and output formatting.
