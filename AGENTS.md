# Repository agreements

## Changes

- Preserve existing user changes and the sibling DazedMTLTool repository.
- Work on the `dev` branch; `main` changes only through `node scripts/release.mjs`.
- Land one feature or fix at a time: merge it into `dev` and verify it there before starting the next.
  Run sessions in parallel only for areas that share no files, and never collect several feature branches to merge together at release time.
- Put problems you notice outside the task under New in the bug list (`~/DazedTranslations/DazedTL-bugs.md`) instead of fixing them; the `dazedtl-triage` skill works through it.
- Run every session and subagent you start or propose on Fable 5.2 (`claude-fable-5-2`, Agent model `fable`) when the work might need it, as the model step of the global `scope` skill lists it (such as highly complex tasks, reworks, causes not found yet and a landing's evaluator), and on Opus 5.5 (`claude-opus-5-5`, Agent model `opus`) otherwise, never Sonnet or Haiku.
  Pass its effort explicitly by how hard the task is: `xhigh` for highly complex tasks and the queue coordinator; `high` for most tasks; `medium` for easier ones, such as a known one-area fix, a merge or a push; `low` for trivial mechanical ones.
  Keep at most two delegated sessions or subagents running at once, and start a follow-up without asking only when it is mandatory: a real bug a user can hit that gives wrong output or text, costs money, loses or corrupts saved data, leaks a credential, or fails a run.
  Put every other follow-up under New in the bug list for triage instead of queuing it.
  A landing's evaluator (dazedtl-land skill, Evaluate step) takes its author's place in the two-agent count while the author waits on it, and counts as one when its author is not itself a delegated session or subagent.
  A session that starts others runs at the highest effort and on the strongest model it hands out, since `start_session` cannot start one above its starter's.
- Before fixing a bug, read the git history of the code involved.
  At a behavior's third fix, propose a rework only if a study shows it does more good than harm (`dazedtl-triage` skill); patch the bug meanwhile, even while a rework is held.
  End each fix commit with an `Introduced-by:` trailer naming the commit that brought the bug in and a `Found-by:` trailer, as [fix-trailers](scripts/fix-trailers.mjs) defines; land.mjs refuses a fix without them, and [review-stats](scripts/review-stats.mjs) reports which landings let bugs through.
- Give each rule one definition, such as how a text block's rows are grouped or how a file's status is counted, and call it from every place that needs it.
  When a fix touches a rule that is defined in more than one place, merge the copies first, or report them if merging is large.
- Follow the ownership boundaries in [architecture](docs/architecture.md) and reuse its shared UI and state mechanisms.
- Keep Guided and Assistant-led in step: when a change adds to one method, check whether the other can take it cleanly and with benefit, by the [method parity rule](docs/architecture.md#translation-execution-and-the-agent-boundary).
- For screens, action handlers or observed state, follow [UI design](docs/ui-design.md), including its rules for every screen and its review checklist, and the [navigation and responsiveness](docs/architecture.md#navigation-and-responsiveness) section.
- Keep credentials, games, run files, logs, and caches outside the source tree.
- Key saved work on its inputs and an explicit version, never on hashes of source files; see [persistence](docs/architecture.md#persistence-and-settings).
- For project-helper connection failures, follow the [sandboxed connection guidance](docs/translation-contract.md#sandboxed-connections).

## Documentation

- Keep each fact in one place and link to the authoritative code or document instead of copying it; the [documentation list](docs/development.md#documentation) says what each document holds.
- Update affected documentation in the same change, at the level of detail the documentation list gives it, and remove obsolete guidance.
  Add a document only for a reader need no existing one serves, and write no feature inventories, function catalogs or progress diaries.
- Add a rule to this file only when most sessions need it and no script can enforce it; otherwise enforce it in a script, or put it in the document or skill where it applies.

## Testing

- Run `node scripts/test.mjs` for foundation or shared behavior changes, and `node scripts/build.mjs` for any code change; it runs the formatting, lint and type checks.
  [Checks](docs/development.md#checks) lists what each covers, focused test commands, and the formatter.
- Run the [live test](docs/development.md#live-test) for platform-specific changes; [platformPaths](scripts/land-lock.mjs) marks their paths (add any it lacks), and land.mjs lands them only once CI passes on Windows and Linux.
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
