# Architecture

This page maps who owns what, the reasons behind decisions, and the rules that span modules.
Behavior that one module owns is described in that module's docstring and pinned by its tests; follow the links.

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
The Guided [workspace hook](../app/src/features/guided/workspace/useGuidedWorkspace.tsx) owns shared state, navigation and action review; each task's body and footer controls come from its [task view](../app/src/features/guided/workspace/tasks/index.ts).
Its backend, [Guided](../backend/dazedtl/translation/guided.py), composes collaborators for [action review and execution](../backend/dazedtl/translation/guided_actions.py), [run inspection](../backend/dazedtl/translation/guided_inspection.py), the [release form](../backend/dazedtl/translation/guided_release.py) and [context setup](../backend/dazedtl/translation/guided_context.py).
Each workflow action is one row of the [action registry](../backend/dazedtl/actions.py), which says how it is reviewed and run and what its review and History call it; Guided's checks, the worker and, through the generated contracts, the renderer read it.
Every change to a game's files goes through the [game-write gateway](../backend/dazedtl/compatibility/game_write.py); its docstring holds the rules.
Files and processes go through the [platform layer](../backend/dazedtl/system.py); see [Windows](#windows).
Working copies are described under [Workflow and shared presentation](#workflow-and-shared-presentation).

## Engine and resources

The adapter retains existing engine behavior while capabilities are extracted incrementally.
Neither checkout is a runtime dependency: the [runtime locator](../backend/dazedtl/compatibility/runtime.py) selects the engine shipped inside this package, independently of cwd and old engine environment variables, with no external-engine fallback.
The runtime was imported from `b91bede18fd2bbd5a9b99f1a866f061bc13865c1` with its [license](../backend/dazedtl/engine/LICENSE.md) and component notices; its historical Python namespaces are internal to the compatibility boundary, and the old UI and application server are not shipped.
Saved manual runs record the [engine version](../backend/dazedtl/engine/desktop/backend/manual.py) that prepared them and resume only on that version; raise it when a change would make a resumed run build requests or parse files differently.
The compatibility layer extends engine behavior only through declared [extension points](../backend/dazedtl/engine/util/extensions.py) and engine settings, never by replacing engine functions; mark an engine function as a point where DazedTL needs to extend it, rather than wrapping it from outside.
The base translation rules in [system.md](../backend/dazedtl/engine/data/skills/system.md), the shared prompt templates, field instructions, base glossary and SFX reference live in the engine's [data](../backend/dazedtl/engine/data) directory.
The base prompt bounds localization to supplied source text to preserve its register without inviting new scene content or assistant responses in game dialogue.
Existing workspace `engine/shared-data` overrides retain precedence and native path validation.
Resources are not seeded into profiles, so future default changes reach new preparations without overwriting customizations; frozen run context stays authoritative for execution and recovery.
Existing phased jobs retain their original engine-owned records and recovery path rather than being rewritten into a different request format.

### RPG Maker text blocks

[rpgmaker_blocks](../backend/dazedtl/engine/util/rpgmaker_blocks.py) is the one definition of how MV/MZ event commands form the text one window shows; translation, the fitter, Text QA, Assistant-led's writer and the release playtest all read blocks there, and its docstring defines blocks, parts and the rows each part owns.
Which comments players read comes from the plugin list the game loads, as JavaScript reads it ([rpgmaker_markers](../backend/dazedtl/engine/util/rpgmaker_markers.py)).
Writers lay text over a block's rows and never add or remove a command, so a saved game's place in an event stays valid and Assistant-led's `rebase_rpgmaker` still lines up.
The playtest's tour gets an index of the blocks before it plays, so a message it sees and the line the static checks list share one identity, the block's first text row.

## Guided runs and paid work

### Estimates and approval

Each phase binds its estimate to source, scope, provider and pricing, guidance, and layout.
Estimate and Batch preparation workspaces are temporary until approval and never enter saved history or contribute translated outputs.
Translate reopens the phase's latest finished estimate while it is current by the [freshness](../backend/dazedtl/engine/util/freshness.py) rule ([unchanged_estimate](../backend/dazedtl/translation/guided_actions.py)), so declining or closing a review costs no second estimate.
A model switch only reprices an estimate ([repricing](../backend/dazedtl/translation/repricing.py)) when the connection and request settings stay the same, a sample request built for each model carries the same messages and the provider counts tokens the same way for every model, which leaves out Claude.
Paid review requires that matching estimate and rechecks its inputs before the native one-use approval controls submission, under the API lock, so other runs cannot revoke it.
Approved work is retained before signaling the worker, and the frozen request then stays authoritative for recovery and is never silently rebuilt.
Navigation never submits work, approval alone never establishes success, and a canceled late reply cannot open a review or start paid work; new remaining work and Live resumes need their own review.
Speaker interpretation stays with the user.
Monitoring and new runs never share a worker: each run has its own controller, and the Batch monitor reads providers on a thread of its own.
Every RPG Maker estimate parses all its files in one worker process, as Batch collection does, and Live translation reuses one worker per concurrent file, because a process per file took seconds each on Windows.

Prompt caching is priced as providers bill it, never as promised savings: a Batch whose provider caches prompts is priced as a range from every shared prefix reused to none, because Batch cache hits are best effort, and an Assistant-led quote's cost is the higher end.
Claude requests cache their instructions for five minutes: a Batch starts most requests together, so many write the cache instead of reading it (two of three real Claude Batches read it on about one request in ten), and a five-minute write costs 1.25 times input where a one-hour write costs twice.
Claude estimates use [Claude's own token count](../backend/dazedtl/engine/util/claude_tokens.py), because Anthropic bills by a tokenizer that turns the same text into more tokens than the GPT-4 encoder other estimates use.
GPT-6.1 Sol Batch quotes use its [published cache rates](https://developers.openai.com/api/docs/models/gpt-6.1-sol) ([batch_pricing](../backend/dazedtl/compatibility/batch_pricing.py)).
A Translate estimate's worker has no credential or network, so [estimate_pricing.py](../backend/dazedtl/compatibility/estimate_pricing.py) counts in a separate process that opens the network only for the count endpoint, with the run's own credential.

Nameplates may hold character names or other display labels, so the names step never assumes a character identity.
It uses Live pricing to avoid waiting for a separate name Batch, the file-text Batch gets its own review afterwards, and collection itself never sends a Live request.
Every name it adds is marked `Unverified nameplate` in the glossary, because it was translated apart from its story: a cameo's 存子 became "Sonko" where its creator reads it Aruko.
Paid names stay reusable whatever happens to the file Batch ([speaker_results](../backend/dazedtl/compatibility/speaker_results.py)) and join the game glossary when collection copies the run's glossary, or once through [publish_names](../backend/dazedtl/translation/guided_runs.py) when the Batch can never complete.

Task completion aggregates verified per-file progress across runs ([translationTaskComplete](../app/src/features/guided/translationView.ts)), so re-running some files keeps the rest; active work, partial or missing output, changed sources and retired runs cannot establish it.
An explicit zero-request estimate is a result, while absent saved request payloads never imply zero work.

### Whole-game estimate

Context's Cost estimate prices every Translate task that sends game text through the API key, over each task's whole file group.
[full_estimate.py](../backend/dazedtl/translation/full_estimate.py) runs it as a tool operation, never as a run, so no approval, history run or paid work can follow from it, and its [worker](../backend/dazedtl/compatibility/full_estimate.py) builds each task's plan with the helpers and request policy a Translate estimate uses, so the figures match.

### Frozen request policies

Each new API run freezes request policies before estimation; a policy joins estimate identity and applies to Live and Batch alike, and runs frozen without it keep their original parser, parameters and request identities.
The parser policies are the constants in [preferences.py](../backend/dazedtl/settings/preferences.py), each documented there, which the parsers ([rpgmakermvmz](../backend/dazedtl/engine/modules/rpgmakermvmz.py)) implement; the clarification retry and compatible state-call grouping ([state_requests](../backend/dazedtl/compatibility/state_requests.py)) define their `POLICY` beside their code.
The [clarification retry](../backend/dazedtl/translation/refusals.py) for provider refusals names the existing fictional source and the owner's adult-character statement without changing source facts or asking the provider to disregard its rules; it is sent once, and repeated refusals stay untranslated.
Page packing (`PAGE_PACKING`) exists because each request otherwise repeats the full system prompt, and Assistant-led organize applies the same 10-line rule (`SHARED_LINES` in [organize.py](../backend/dazedtl/translation/organize.py)).

### Batch execution and recovery

Uncertain work is never resubmitted automatically, and an app restart needs no second approval for an unchanged approved queue.
A Batch approval binds the full frozen queue and plan; only the owning worker advances it, and the backend-owned [Batch monitor](../backend/dazedtl/translation/batch_monitor.py) restarts that worker after an interruption and collects its responses, independently of the current screen.
Explicit stops, provider cancellations, newer approved overlapping runs, changed scope and uncertain submissions prevent automatic continuation.
Requests read as never sent only with evidence the [submission journal](../backend/dazedtl/compatibility/batch_continuation.py) or the [transport observer](../backend/dazedtl/compatibility/transmission.py) records, since SDK retries can hide a processed try behind a later refused connection.
Automatic local consumption requires a durable fetched marker and submission receipts covering every prepared request, so collecting one chunk cannot turn an unsent remainder into a full consume pass, and a failed consume offers Retry saving results instead of a restart loop.
The [OpenAI Batch window](../backend/dazedtl/compatibility/batch_window.py) gives each provider job at most a quarter of the input-token allowance, so a slow request cannot hold the whole window.
Provider reads and downloads run outside the API lock and feed the application observer through cached observations.

### Evidence and validation

Evidence is kept apart from accepted values: response bodies, refusal metadata, request mappings and native validation receipts ([batch_validation](../backend/dazedtl/compatibility/batch_validation.py)) are retained before validation or scratch cleanup, bound to request key, source, file and response hash.
Missing evidence never establishes successful validation or billed usage, and provider completion stays separate from saving local output.
A refusal cannot enter game dialogue; a Guided phase puts the source back for lines older runs saved a refusal note in ([saved_refusals](../backend/dazedtl/translation/saved_refusals.py)), since a run sends only lines still in the game's own words.
An old interrupted Live run without request evidence flags only its shared files and phase in the overlap advisory, since its send outcomes cannot be rebuilt locally.
Readers for older runs ([live_validation](../backend/dazedtl/compatibility/live_validation.py), [choice_history](../backend/dazedtl/compatibility/choice_history.py)) settle a historical request only when the frozen plan, output hashes, submission mapping and exact source identity all match; otherwise it stays unresolved, and missing bodies are never invented.
Grouping a retry with its original is presentation only: receipt indices, submission guards and billed usage stay intact.

### Result reuse

Workers record source identities independent of model, prompt and chunk size with their validated values, and continuation reuses them per text identity, never as a file-complete skip, while the source bindings and file versions match; the newest compatible run wins.
The Live names pass before a Batch belongs to no file, so it never counts toward a file's lines or continuation reuse.

### Run history and inspection

Run history is the single run list, and its shared [run inspector](../app/src/features/guided/RunInspector.tsx) owns cancellation, queue controls, collection recovery and reviewed reapplication, rendering the observer's receipts without another polling loop.
Approved project-owned runs stay in History, failed and canceled ones included; the native pointer is not the ownership registry.
Saved run status never vetoes an explicitly requested new translation: overlapping submitted or uncertain requests get an advisory about possible duplicate charges in the cost review instead of an extra confirmation, and automatic recovery never gains authority to resend them.
Display rules never settle submissions or release execution guards, and the observed `workerStatus` keeps the real worker state, so a background check cannot promote an older run.
Per-file cost and time, and Other event text's lines, come from native result receipts; request rows, payloads and logs stay out of observations and browser preferences.

### File status and Lines

Database files and Maps & events read each file's status and Lines from the file itself through [file_lines](../backend/dazedtl/translation/file_lines.py), independently of selection and of the runs that wrote it.
What an event file holds is defined once in [rpgmaker_scope](../backend/dazedtl/engine/util/rpgmaker_scope.py), which the engine translates from, and a line is left while it holds Japanese by the engine's own rule ([source_text](../backend/dazedtl/engine/util/source_text.py)) or a refusal note, whatever its `_original` says.
The engine probe ([engine_runtime](../tests/fixtures/engine_runtime.py)) checks that the engine sends exactly the lines this counts as left, and nothing on a second pass, so the count and the engine cannot drift apart.

### Apply and release

Text Apply is a full overwrite: it binds the frozen candidates by hash while accepting intervening game-data edits, names the files it replaces edits in, and backs up what it overwrites before its first write.
Its review lists files without comparing their text, which took minutes on a large game; a restore's review shows the [diff](../backend/dazedtl/compatibility/text.py).
Applying never settles request receipts, cancels work or establishes translation completion, and Reapply uses a run's hash-verified retained output, never the latest working translation.
Translation, Apply, Assistant-led's writes, Text QA and new Line widths fit text with one [fitter](../backend/dazedtl/engine/util/rpgmaker_rewrap.py), so text written by one never needs fitting by the next and Check has no line width task.
New Line widths queue a `fit_text` publication ([text_fit](../backend/dazedtl/translation/text_fit.py)) that rewraps only lines that no longer fit in files DazedTL applied, so hand layout that fits stays; its result lists the text no wrap fits, which Guided's Line widths shows while the widths and the game's text are unchanged.
Release freezes the runtime scope and original-source bindings through an app-only, one-use preview; the clean packager ships, besides the runtime scope, only files a saved game snapshot holds, so a translator's notes and downloads stay out.
A VX Ace game ZIP's name must be ASCII: RGSS3's Game.exe reaches its library through the ANSI code page and fails as "RGSS301.dll File corrupted" from a Japanese-named folder on English Windows, and Explorer's Extract All adds a folder of the archive's name.
The GameUpdate config belongs to the engine's [gameupdate_config](../backend/dazedtl/engine/util/gameupdate_config.py), and the [action guard](../backend/dazedtl/engine/desktop/backend/workflow_actions.py) leaves its settings record out, so writing it never marks saved work Outdated.
Neither Apply nor packaging manufactures a user-review record or completes Len's report-based QA, and the project helper cannot invoke Guided packaging.

## Plugins and images

The [plugin service](../backend/dazedtl/plugins/service.py) owns retained investigation, working copies and checked publication for MV/MZ plugins and VX Ace's Ruby scripts in `ace_json/scripts`.
The assistant decides which plugin text players see and the user reviews neither files nor strings, so Apply to game writes every checked file in one click, checking and backing up each first.
An Acorn AST inventory binds reports to exact source bytes without evaluating plugin code; the [Ruby reader](../backend/dazedtl/plugins/ruby.py) gives Ace's script literals the same inventory in Python, so no Ruby ships.
Original Japanese comes from a verified source backup even after runtime JSON has been translated, so a task cannot start without it.
Lookup values, code keys, expressions, serialization structure and control tokens stay protected by the app and are never asked about.
One copied task covers every plugin file through the [project helper](translation-contract.md#project-helper); each result stays bound to the request that asked for it, and the helper cannot preview or restore runtime files; only the final check's assistant may apply, through the same Apply to game path.
Labels Text QA's capture found squeezed in a plugin file come to Plugin files, because QA never writes plugin files; the assistant shortens each in a copy of its own and confirms it on screen in the [game window](../backend/dazedtl/engine/util/rpgmaker_window/launcher.cjs) with the copies served in place of the game's files.

The [image service](../backend/dazedtl/images/service.py) owns a project-scoped SQLite inventory, selection, discovery and editing contracts, saved reports and application receipts shared by Guided and Image Manager.
The renderer reads metadata in bounded windows and thumbnails through a [queue](../app/src/features/images/thumbnails.ts); the [server](../backend/dazedtl/api/server.py) answers previews on a few workers outside the engine context, which redirects stdout process-wide, while every other request runs in turn.
The selection is the list to translate, walked through the four steps of [imageFlow](../app/src/features/images/imageFlow.ts): the assistant investigates, the user chooses, the assistant translates, the user applies.
Detector misses alone cannot certify that an image has no text, and only byte-identical sources reuse discovery evidence; lettered sound effects are flavor, often hundreds per game, so an image with nothing else stays out of the list.
Every image an assistant changes needs a [recipe](../backend/dazedtl/images/recipes.py), so a later sibling starts from it instead of pixels, and reading a report runs the same [validation](../backend/dazedtl/images/validation.py) as the assistant's validator; only the user can accept an image the assistant cannot prove.
The app never runs a recipe's command, so code in the game folder runs only in the assistant's own process.
Apply freezes the batch in a one-use preview, journals the reviewed hashes before writing and attempts rollback on failure; preserved originals support reviewed restore.
The [background solver](../backend/dazedtl/images/background.py) rebuilds a backdrop from its [family](../backend/dazedtl/images/families.py) of same-size images instead of inpainting it, and the [image text editor](../backend/dazedtl/images/editor.py) uses only installed offline resources and deterministic fills, never a hosted fallback or model download.

Plugin and image progress in the game folder belongs to the project that saved it, and projects are keyed by source path, so a moved or copied game, a new profile or a reinstall opens that work under a new project; [foreign_work](../backend/dazedtl/foreign_work.py) reports it, and nothing is used or moved until the user chooses.

## UI and state decisions

### UX principles

Strive for [Nielsen's ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) when designing and reviewing this tool.
Make current state and the next useful action visible; use translation tasks and familiar language; offer clear exits and recovery; keep shared controls consistent; prevent scope and spending mistakes; make prerequisites visible instead of requiring memory; support both guided and experienced use; prioritize relevant actions; give errors a practical recovery path; and put concise help beside the task that needs it.
Use these principles to evaluate real workflows, rather than adding extra panels or confirmation steps to satisfy a checklist.
Give each idea one name and keep it everywhere: Apply only means writing into the game (settings are saved or used); Backups are copies you can restore and Versions are the Git history used to merge game updates; Line widths are the per-line character limits DazedTL wraps translated text to, with the rows a message window shows.
Assistant-led is the UI name of the method built on Len's game-translation skills; code and records keep the `len` identifier.
Its starting prompt runs the whole method without the user: it asks only for spending approval, a missing API connection, denied access or a decision no source evidence settles, and a check it cannot make stays pending instead of stopping the run.

### Visual design

The app ships [Inter](../app/src/assets/fonts/Inter-OFL.txt), so text widths and wrapping match on every platform; system fonts only supply scripts it lacks, Japanese faces first, so game text keeps Japanese kanji forms.
The rounded [Fredoka](../app/src/assets/fonts/Fredoka-OFL.txt) sets only the wordmark and page titles, through `--font-family-display`.
Every literal font size, weight, color, spacing step and radius lives in [tokens.css](../app/src/styles/tokens.css); [styles.mjs](../scripts/styles.mjs), part of the build checks, rejects literals in any other stylesheet, so a new value starts as a named token.

- Type: five sizes and three weights (page titles; task, dialog and section titles; body text and row titles; secondary text and controls; captions); headings and emphasis semibold, row titles medium, everything else regular.
- Headings: each region has one, never a stack of headings before content; headings inside a dialog body sit a step below the dialog title.
- Measure: paragraphs and notes stop at `--measure`, about 72 characters; tables, editors, grids and row labels keep the width their layout gives them.
- Forms: labels stack above controls, except Settings and dialog forms, which use a label column; related checkboxes share one label in [CheckGroup](../app/src/ui/FieldRow.tsx) and line up in columns; choices and short values are at most 24rem wide, paths, search and free text use the wide variant.
- Controls: buttons, single-line inputs and selects share `--control-height` and `--control-radius`, so a field and its button line up.
  Pick a control by the choice it offers: a checkbox for on or off, [SegmentedControl](../app/src/ui/SegmentedControl.tsx) for one of a few short options, [OptionCards](../app/src/ui/OptionCards.tsx) for one of a few that each need a line of explanation, a select for longer lists, and [ComboBox](../app/src/ui/ComboBox.tsx) when a typed value is also allowed.
- Spacing: 4px `--space-*` steps, 8 inside a group, 16 between rows and 24 to 32 between sections; `--space-half` only nudges small marks, and 1px only aligns borders.
- Corners and depth: `--control-radius` for controls and small marks, `--panel-radius` for panels, `--dialog-radius` for dialogs; popovers and menus share `--shadow-popover`, dialogs use `--shadow-dialog` over `--color-backdrop`.
- Color: teal-tinted neutrals with a cyan-green accent, so the app reads as its own tool; done marks use a leaf green so finished never looks selected.
  Accent marks interactive text, focus and the edge or underline of what is current; accent strong sits under white text on the one primary button; accent subtle marks selected surfaces.
  Green, amber and red mark status (and a diff's added and removed sides), always with text or an icon; image canvases keep their own `--color-canvas-*` and `--color-mark-*`, because they are drawn over game images.
- Brand: the dazed cat, drawn from the original icon, is the teal tile as the window icon and its accent outline in the top bar and the Project page's welcome row, nowhere else, so it stays distinctive.
- Icons appear in navigation, on actions that leave the app, on menus and disclosures, and on Add; other actions are text only.
- Footers start with Back and end with Continue; the task's own action sits just left of Continue and is the primary until the task is done, then Continue is, so each screen has one primary.
- Placement: a task's main action lives in its footer, rows hold supporting actions, and headers hold task-wide views or settings; a task's purpose is its one-line TaskHeader description; consequences sit in the review dialog of the action they qualify, a precondition beside its action, background in a help popover beside what it explains, and status stays visible.
- Small windows: below 1100px wide the sidebar becomes a rail of icons over short labels, and windows 720px tall or shorter compact the top bar and footers.

### Workflow and shared presentation

Use the flat, compact [Settings](../app/src/features/settings/Settings.tsx) and [Project page](../app/src/features/project/ProjectPage.tsx) implementations as page examples.

#### Places and surfaces

The sidebar has three places: the Project page holds everything about the game, Translation holds the work, and Settings holds the app.
Each game has one translation method, chosen in [MethodDialog](../app/src/features/project/MethodDialog.tsx) and kept in the project registry; changing it keeps the other method's work, and the Project page's Status, History, Versions and Backups tabs serve both.
Screens use four kinds of surface, each with one job:

- A page is somewhere you work or browse, reached from the sidebar and kept when you leave and return.
- A tab is another view of the same thing, and switching never loses your place or drafts.
- A dialog holds one decision or one focused edit and ends in an explicit choice; it never opens another dialog except a detail view that returns to it, and a dialog that leads to a review closes before the review opens.
- A menu is a short list of choices that closes when you pick one.

New pages start from one of three templates: the task page (stepper, task tabs, TaskHeader, the task's panels, its work area, footer), the editor page that Settings, the Project page and [Assistant-led](../app/src/features/translation/Translation.tsx) share (header, tabs, a scrolling body and footer per tab), and the decision dialog (the decision as its title, what will happen, explicit footer choices).
Editing footers sit outside scrolling content.
Sheets and inspectors close with the header's one close button; decisions such as spending reviews, resyncs and Apply have no close button and end with explicit footer choices.
Reserve cards for content requiring a distinct container; tables, editors and the image grid stay unboxed.

#### Layout

Every stylesheet loads through [index.css](../app/src/styles/index.css) in a cascade layer (tokens, base, shared UI, the app shell layout, then features), so a feature's rules override shared primitives regardless of specificity; keep selectors simple instead of raising specificity to win.
Layouts must remain readable and usable from small laptop monitors to large 4K monitors or TVs: reflow content from the available window space and display scaling, keep actions reachable on small displays, and use large ones without excessive stretching or gaps.
Every page centers one content column, `--content-width`; a workspace whose grid and preview use every pixel, the Images task, is a wide [PageLayout](../app/src/ui/PageLayout.tsx) instead.
Frame rows (page headers, stage strip, task tabs, messages, scrolling bodies and footers) span the window and pad their content to that column, and rows that do not scroll reserve the body's scrollbar gutter, so every edge matches across screens and window sizes.
Fill editors and file lists keep a minimum height and the body scrolls instead; a dialog whose tabs differ in height stacks them with [StackedTabPanels](../app/src/ui/Tabs.tsx), so switching tabs keeps its size; rows grow with feedback rather than fixing heights or clipping content.

#### Shared components

Compose shared primitives with design tokens, and fix a reusable layout defect in the primitive, not per screen:
[ActionList and ActionRow](../app/src/ui/ActionList.tsx) for repeated label and action rows, [Menu](../app/src/ui/Menu.tsx) for action lists that open from a button, [ComboBox](../app/src/ui/ComboBox.tsx) for editable suggestions, [Modal](../app/src/ui/Modal.tsx) with [DialogHeader and DialogBody](../app/src/ui/Dialog.tsx) for dialogs, [JobStatus](../app/src/ui/JobStatus.tsx) for operation summaries, [StatusMark](../app/src/ui/StatusMark.tsx) and [StatusIcon](../app/src/ui/StatusIcon.tsx) for status, [Notice](../app/src/ui/Notice.tsx) for inline notes, [StatusPanel](../app/src/ui/StatusPanel.tsx) for work that is not the user's own, [FileName](../app/src/ui/FileName.tsx), [PathInput](../app/src/ui/PathInput.tsx) and [PathText](../app/src/ui/PathText.tsx) for names and paths, and [ActionSlot](../app/src/ui/ActionSlot.tsx) for a tab's footer action.
Shortcuts come from [useShortcut](../app/src/state/useShortcut.ts), scoped to the visible screen and the top dialog; nothing that spends, applies or packages gets a shortcut.

#### Status and feedback

Work items say where they stand in one vocabulary, the display states in [displayStatus.ts](../app/src/ui/displayStatus.ts), each with one mark; each feature maps its own states there and keeps its specific reason in the item's detail, and backend state machines are unchanged.
Waiting means the work is with an assistant, never that the app is running something; Done is finished work that never writes into the game; Outdated marks a saved result whose basis changed before it went into the game, while edits after a result is applied are expected and leave it as it was.
Action controls pair the shared pending button and status feedback with `useAction`'s guarded action key; a result or disabled reason sits beside its own control, so buttons keep their place and bars keep their height.
Saved operation indexes carry their action identity, so feedback stays beside the right control after navigation or restart, and [FeedbackOwners](../app/src/ui/FeedbackOwners.tsx) lets a page's fallback message show only errors no mounted control reports.
Keep failures beside their action or in the run or file inspector; never aggregate historical errors into page-wide reminders or counters.
Saved results, worker logs, frozen scope and record identifiers belong to the inspector's Technical view, not routine views.

#### Guided stages and tasks

Translation follows the working Qt GUI's task order through [workflow.ts](../app/src/features/guided/workflow.ts), grouped into five stages: Set up, Context, Translate, Check and Release.
A stage holds the tasks that share its purpose, so no stage exists only to host one optional workspace, and optional work never holds up the next step.
A stage of optional tasks only is done once opened with every required task before it done, because looking at what it offers is all it asks.
Tabs and Continue keep drafts and allow navigation regardless of completion; they never save review receipts or complete skipped tasks, and status checks stay at execution and explicit save boundaries.
Set up's one action runs the backup, file preparation and version baseline as separate steps, each through its own preview and execution, so every step keeps its checks and receipts.
Routine setup steps and local estimation consume their preview right after the click; replacement backups, paid work, runtime replacement and file resync keep their review.
The original-backup record lives in the profile while snapshots live in the game's own store, so a moved or copied game is offered its earliest snapshot as the original (`use_source_backup`) instead of saving its current, possibly translated, files.
Each task applies its own work and shows what it has not applied, with no cross-task reminder list; applied Translate output has no restore of its own, since Versions and Backups undo it.

#### Working copies

The selected phase files bind each new run and each application preview.
Working copies are seeded from current game bytes and kept across navigation, estimates and restarts; original-branch identities stay reference and recovery bindings and never force working copies back to untranslated text.
Resync is a reviewed replacement of the checked files with their game bytes that archives their working copies, staged outputs and variable cache first, and advances per-file versions before replacing, so earlier runs cannot overwrite resynced files or supply stale cached responses even if resync is interrupted.

#### Assistant tasks

Every task that hands work to an assistant shows the shared [AssistantTask](../app/src/ui/AssistantTask.tsx) panel, which reports only copied instructions or saved findings, never an external process inferred from a click.
The [Application](../backend/dazedtl/api/server.py) records each copy's handoff in the [assistant task registry](../backend/dazedtl/translation/assistant_tasks.py), so features keep their own requests, reports and validation, and [assistantTasks.ts](../app/src/features/assistant/assistantTasks.ts) derives one display state per task for the Project page, the top bar and the feature's panel.
Saved findings stay a record of the source they inspected, and a saved scan that is no longer current names why, because a setup task that could not see the reason rewrote valid findings after each unrelated commit.
Speaker findings ([speaker_setup.py](../backend/dazedtl/translation/speaker_setup.py)) enable only confirmed rules on verified source hashes, and the scan runs in an isolated worker without credentials or network access and never translates names; the setup assistant's header [review](../backend/dazedtl/translation/header_review.py) writes only the fixed headers and records each decision, so the user reviews nothing.
Event text findings ([event_text](../backend/dazedtl/translation/event_text.py)) bind to the selected files, original data, plugin dependencies and the installed parser's registry, not the rest of the engine module, which most releases change; text no handler captures gets the game's own [custom patterns](../backend/dazedtl/engine/util/custom_patterns.py) instead of an engine change.

#### Assistant-led

Its API run panel holds the assistant's estimate and its button is the only approval: the project helper resumes only runs the user approved there, and each new estimate replaces the one waiting ([newest_estimate](../backend/dazedtl/translation/jobs.py)).
The assistant's own plan pays for every turn, so new games start on API Batch, or Live when the connection cannot batch.
Start over moves the attempt, its Git history and the playtest's fixes to `.dazedtl/archived` instead of deleting them, after saving backups; only the user can start it, so the project helper has no route to it.

#### Publication

The [text publication journal](../backend/dazedtl/translation/publication.py) freezes reviewed destinations and both byte versions before any runtime replacement, and the worker fits, preflights and publishes the whole batch with verified backups and rollback attempts.
A batch that could not roll back raises a notice on every Guided task, because part of it may be in the game; a batch restores once no later batch still in the game changed the same files, and only its own Apply receipt entries go back.

#### Text QA

Text QA and the release playtest are optional and never prerequisites for navigation or Release.
One [QA policy](../backend/dazedtl/engine/data/skills/rpgmaker_translation_qa.md) makes the task README, every reviewer brief and the copied handoff, so they cannot disagree about applying; the [design](text-qa-redesign.md) holds the goals, decisions and evidence.
The [QA engine](../backend/dazedtl/engine/util/qa/__init__.py) owns stages, bundles, workers, declines, observations, findings and the review ledger; content is never classified or excluded in advance, and declined lines are set aside only once a second helper declines them or none other will.
Its [preflight](../backend/dazedtl/engine/util/rpgmaker_qa_preflight.py) reports Japanese that was never translated, with its [reach](../backend/dazedtl/engine/util/rpgmaker_qa_reach.py), so the gap is shown rather than silent, but QA neither reviews it nor blocks on it, and it leaves out what Plugin files keeps in Japanese on purpose.
Corrections pass the engine's correction and regression checks on disposable copies before publication, and each is fitted by the one fitter, so findings store what the game gets.
[Lint](../backend/dazedtl/engine/util/rpgmaker_qa_lint.py) marks a family automatic only when its fix was right on every line it matched in ten released games and changes no line break or code; the others need a reviewer, because an apostrophe can be a moan's or a slur's, a title needs the whole game's titles, list and label fixes change line breaks, and level-tag spacing matched no real defect.
Its glossary family replaced two checks: the Guided Glossary check, which flagged 7,631 lines on ten games for the user to sort, and QA's database glossary check, which sent 175 database texts to deep review, mostly 回復 in descriptions; it proposes 150 fixes there, nearly all renamings and drift such as "Shinnaisamu" for Sinnaysam, none automatic since about one in ten was a judgment call, and a recorded decision wins over the glossary row it disputes.
Release QA applies its finished findings without asking, as one `qa_apply` text batch that History can restore ([text_qa](../backend/dazedtl/translation/text_qa.py)); apply waits only for questions, each carrying a proposal, and no QA command writes game files itself or pushes.
Preparing QA captures the interface screens in the [game window](../backend/dazedtl/engine/util/rpgmaker_window/launcher.cjs), which serves the game folder read-only to offscreen windows in an in-memory session with no network, so nothing reaches the game's saves; squeezed text in a plugin file goes to Plugin files in Guided, and to the assistant through the helper's `qa` status in Assistant-led, because QA never writes plugin files.
Deep bundles print each scene once, which cut deep review's text from 14.4 MB to 3.3 MB on the Arina run.
The playtest's [checks](../backend/dazedtl/engine/util/playtest/checks.py) and [tour](../backend/dazedtl/engine/util/playtest/harness/main.cjs) report problems in lines QA reviews as observations of a `playtest` worker, so findings never make another task; [its design](text-qa-redesign.md#release-playtest) holds the decisions.
The assistant's [fixes plugin](../backend/dazedtl/engine/util/playtest/fixes.py) is written only after a play with it passes and joins every patch's manifest, since a manifest without it would drop the fixes without an error; QA's apply and the fix each wait while the other's changes are in no version, since a version takes every change in the game.

### Navigation and responsiveness

Project identity, execution mode, and visible screen are separate; registry upgrades retain existing IDs, job references, phase selections and recovery data.
`useApplication` supplies shared state through one observer; feature polling loops would introduce competing reads.
The application provider supplies its API and browser event subscriptions; the observer owns response ordering and refresh scheduling.
The shared [navigation state](../app/src/app/navigation.ts) owns the visible screen and per-project workflow views independently of backend observations, so a background read cannot move the user back.
Workflow tasks, document tabs and event-code views are small browser-profile preferences, written before the view changes; they contain no game text, drafts or execution authority.
Task Options panels configure the task in place; they must not act as navigation menus to other phases.
Keep cross-task navigation in the phase/task controls, and reuse settings controls inside the owning task's panel.
Route application screens and Guided workflow locations through the shared navigation methods exposed by `useApplication`; keep feature-local view choices in their owning UI state.
Switching an already-loaded view with clean drafts must not require a Python request or await a project snapshot.
Retain usable page data across revisits where its ownership and invalidation rules permit; scope any missing-data load and its pending feedback to the feature that needs it.
[App](../app/src/app/App.tsx) and the [Guided workspace hook](../app/src/features/guided/workspace/useGuidedWorkspace.tsx) provide working examples.
Automatic refreshes yield to the next operation in a chained action, so saving a draft and then navigating does not insert a discarded project read between them.
Give `useAction` the application as its `observer` when its completion needs updated observed state: it waits only for an observation of API mutations the action began.
Reserve `application.refresh` for an intentional re-read, such as an explicit reload control, and do not attach an unconditional whole-project refresh to every button.
Views that show their own replies before the next observation use [`useObserved`](../app/src/state/useObserved.ts): a newer snapshot replaces a reply during render but waits while unsaved edits or actions build on the current revision.
An open project stays observable while no app worker is active, so external assistant reports become visible; observation ends only when the backend stops or is incompatible, and any other failed read is retried after a growing delay.

Observations stay small: new observation work uses bounded summaries or cached derivations with explicit invalidation, and authoritative source, artifact and spending checks stay at execution or explicit inspection boundaries.
Do not add whole-game parsing, a process per file or full request-history reconstruction to a polling snapshot; cached display state never authorizes paid work or file publication.
A poll checks every saved run, so a digest cache it reads on every poll must keep that whole working set: one bounded below a long run history rereads every file on every poll.
[ObservedFiles](../backend/dazedtl/translation/files.py) and [Digests](../backend/dazedtl/engine/util/freshness.py) reuse a file's digest while its stat signature holds, and run views and request rows come from bounded [process summaries](../backend/dazedtl/compatibility/process_view.py).
Requests, the project helper's included, run one at a time behind the lock every snapshot needs, so work that takes seconds on a big game starts an operation worker instead of running in the request.
Measure nontrivial additions with representative generated data.
Backend disconnection invalidates pending reads, so a late response cannot restore an obsolete connected state.

`useAction` guards duplicate submissions, while `useDraft` serializes recovery writes and explicit saves.
Recovery drafts remain dirty until committed; leave guards flush them before navigation and close.
Autosaving editors, such as Image Manager and the image text editor, save every write instead, so a successful write becomes their clean baseline.
Mutations changing snapshot-backed state, including recovery drafts, must keep the default `refresh` in their [method contract](../backend/dazedtl/api/contracts/methods.py), so remounted editors cannot recover an older draft from the cached snapshot.
Never retry writes automatically, since some actions submit paid work.
Task and screen error boundaries isolate render failures from navigation and the observer; explicit retries and interface reloads flush retained draft guards before remounting.
Plugins is bundled with the other screens so rebuilding the desktop app cannot remove a deferred chunk still needed by an open window.
Electron owns the native renderer-crash/unresponsive dialog and reloads only on explicit user choice, keeping the existing Python process and job ownership.

### Persistence and settings

Project-format changes increment `SCHEMA_VERSION` and register consecutive upgrades in [projects/store.py](../backend/dazedtl/projects/store.py); [`read_versioned_json`](../backend/dazedtl/storage.py) validates the result, backs up the original bytes and replaces the file atomically.
Whether saved work is still current has one rule, explained in [freshness](../backend/dazedtl/engine/util/freshness.py): saved work is keyed on its inputs and an explicit version, never on hashes of source files, so an update alone never outdates it.
A Text QA task is keyed the same way, on what it reviews and `QA_RULES_VERSION` in [qa/schema](../backend/dazedtl/engine/util/qa/schema.py), bumped only for a change that makes saved reviews wrong or unreadable; the [previous-release QA check](development.md#previous-release-qa-check) fails when a change breaks the previous release's tasks without that bump.
Portable workflow options live in the game's .dazedtl/len-method/workflow.json and snapshots in its .dazedtl/backups/v2 store; guidance stays in the game's own files; the app profile holds connections, recoverable drafts, run plans and receipts, and older full-copy backups.
Project opening and selection publish their in-memory ownership only after backend persistence succeeds, and removing a game from the recent list hides its record instead of deleting it, so its runs keep their owner.
Engine-owned settings and run formats remain the adapter's responsibility.

Diagnostics record only fixed metadata and relative code locations, never exception messages, payloads or raw stderr, and keep only failures the interface reports generically, so explained refusals cannot push them out of the bounded report.
Hangs throw nothing, so a [watchdog](../backend/dazedtl/watchdog.py) records them, and workers, whose standard error goes to their run log or nowhere, record their own failures through the [diagnostics](../backend/dazedtl/diagnostics.py) hooks.
The report names the checkout revision and whether tracked files changed, since code locations resolve only against that revision.

Connections and preferences share one atomic record in workspace `settings/settings.json`.
Saved secrets never enter renderer responses or recovery drafts, and model drafts are bound to connection IDs.
The public preference schema is [preferences.py](../backend/dazedtl/settings/preferences.py); legacy engine values are kept privately through a backed-up versioned upgrade and materialized only before engine actions.
Provider presets declare their transport protocol independently of their identity, such as Kimi on OpenAI's formats and OpenRouter's own [Batch transport](../backend/dazedtl/compatibility/openrouter_batch.py) on the engine's Batch provider points.
Existing connections and frozen runs keep their original identity and route; runs resolve credentials by the connection's recorded runtime name, so removing a connection strands its unfinished runs.
Settings that change requests, such as an OpenRouter host, structured outputs, token budgets and rates, freeze into each new plan before estimate hashing through the [request adapter](../backend/dazedtl/compatibility/request_parameters.py) and [worker adapter](../backend/dazedtl/compatibility/worker_policy.py), so a settings change cannot redirect or reprice a resumed run.
Prices are looked up outside the application lock only when preparing, reviewing or approving work; snapshots use prices already looked up ([model_defaults](../backend/dazedtl/compatibility/model_defaults.py)), and public listings never establish account eligibility.

### Notifications

[WorkAlerts](../app/src/app/workAlerts.ts) reads every observation the store publishes, outside rendering, so a window in the background still notices; its docstring says which work calls the user back.
The main process shows the desktop notification only while the window is not focused; on Windows a notification shows under the Start menu shortcut carrying the app's ID, so the main process gives the launcher's shortcut that ID and removes the `Electron.lnk` Electron writes, which would open a bare Electron.

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

The generated starting prompt uses scripts/project.py against an authenticated loopback endpoint in the running backend, whose connection descriptor is local to the profile, permission-restricted and removed on shutdown; its token is never embedded in a handoff.
Agent operations use the same locked dispatch and project/run ownership checks as Electron; the helper has no settings or general shell endpoint.
The app controls its workers; external assistant activity is reported from saved artifacts and must not be represented as an app-owned process.
On Windows every copied task opens with a [note](../backend/dazedtl/translation/helper_command.py) naming DazedTL's own Python with `-X utf8` and its bundled Git, because a fresh Windows has neither on `PATH`, and Python writes pipes in the ANSI code page, which cannot hold the Japanese an assistant's scripts print.

A compiled plan freezes sources, full context, field constraints, provider parameters, rates and connection identity, and the run's record and approval bind the plan file's exact bytes ([plan_file](../backend/dazedtl/translation/plan_file.py)).
Tracked game sources bind to their original-branch blobs; untracked exports, guidance and the plan file bind to their exact bytes.
Organize derives plans from engine-neutral source units that Len's extractor saves, so parsing and injection stay in Len's per-engine tools and the assistant never rewrites the game's text; a census from the prepared source backup decides scope, so the extractor cannot narrow it.
Organize and compile run in an operation worker ([run_compiler](../backend/dazedtl/translation/run_compiler.py)), and the run's worker compiles every request again and compares before it sends anything, so a big plan never holds the app's other requests.
Accepted results are keyed by logical source and context rather than Japanese text alone, and frozen plans and approvals are never migrated in place.
Submission intent is durable before provider calls and raw receipts before acceptance; for compiled plans an uncertain submission blocks overlapping work.
Approval receipts bind the project, immutable plan and quote with a profile-local signature; a saved boolean alone cannot authorize a worker.
Workers hold per-run locks and stop issuing work after losing their owning process; closing asks them to stop at a checkpoint and then ends any still running with the processes they started, so a hung Git command cannot keep holding the game.
An ended worker cannot clean up after itself, so each run worker keeps its temporary files in a [folder of its own](../backend/dazedtl/translation/jobs.py) that the app removes once it sees the worker gone.
Closing or pausing cannot undo an already submitted provider request.

Git baselines and backup records gate new translation work, and the game-write gateway refuses writes while the checkout is off the translation branch or mid-operation; [checkout_issue](../backend/dazedtl/translation/operations.py) names the problem for both the refusal and the warning every Guided task shows.
Reviewed runtime manifests control patch scope, and all .dazedtl work stays outside both branches.
DazedTL's own runtime files a game holds join every manifest ([dazedtl_files](../backend/dazedtl/engine/util/len_patch_scope.py)), because an assistant's manifest of data and `plugins.js` alone once gave players a `plugins.js` loading a plugin the patch lacked.
Official game updates are staged and merged by [version_update](../backend/dazedtl/engine/util/version_update), whose modules explain why each kind of file merges as it does; a local delivery packages only reviewed Git files, and public publication remains a separate action.

VX Ace preparation runs in Python on every platform: [util/ace](../backend/dazedtl/engine/util/ace) ports RV2JSON 1.2.1 and RPGMakerDecrypter's archive reading instead of shipping their Windows executables, and [the Ace fixture](../tests/fixtures/ace/regenerate.py) records RV2JSON's own output, so conversion tests need neither Ruby nor real games.
RGSS3 reads only the archive while `Game.rgss3a` exists, so Set up keeps an encrypted game's archive in `.dazedtl/ace`, out of releases and Git, and patches carry it rebuilt from the game's current files.
The game reads only Data, so the game-write gateway packs what a write changed in `ace_json` ([pack_ace](../backend/dazedtl/compatibility/guided.py)), and Release requires a current packing receipt.
Ace data is translated by the MV/MZ engine with its `VXACE` option set from the project's engine ([phase_workflow](../backend/dazedtl/engine/desktop/backend/workflow.py)), so frozen plans carry it.

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
