# Architecture

Who owns what, the rules that span modules, and the decisions behind them.
Behavior one module owns is described in its docstring and pinned by its tests; follow the links.

## Ownership

| Location | Responsibility |
| --- | --- |
| [app/src/app](../app/src/app) | Shell, navigation, and the single application/job observer |
| [app/src/features](../app/src/features) | Each feature's components, hooks, and styles |
| [app/src/ui](../app/src/ui), [styles](../app/src/styles) | Shared presentation, design tokens, and layout |
| [app/src/state](../app/src/state) | Action feedback, serialized drafts, and leave guards |
| [app/src/api](../app/src/api) | Typed contracts, transport, and named application operations |
| [app/electron](../app/electron) | Native dialogs, approved folder opening, close handshake, Python process, update controller and the [user guide's](../app/electron/guide.cjs) file and links |
| [backend/dazedtl](../backend/dazedtl) | Project identity, settings, workflow actions, and run ownership |
| [compatibility](../backend/dazedtl/compatibility) | The only boundary allowed to import the bundled engine |
| [engine](../backend/dazedtl/engine) | Preserved parsers, worker implementation, native tools and translation toolkit |

- The shell composes features; features use shared services without importing each other's internals, and shared UI components neither import features nor call the backend.
- The renderer is sandboxed, with no filesystem, process or network access.
- The Qt GUI from `DazedMTLTool` is the reference for Guided's workflow order and behavior; its retired Electron interface is not a UX reference.
- The Translation service owns project operations, request plans, accepted results and run recovery, for the UI and the project helper alike.
- Len's skills own engine investigation and methodology for Assistant-led, with the compatibility layer's context, Git, preparation, injection and provider helpers; the preserved runner owns parsing, speaker preparation, phase profiles, glossary collection and Batch receipts; app workers own the record of original game files, Git baselines, checkpoints and patch packaging for both methods.
- The Guided [workspace hook](../app/src/features/guided/workspace/useGuidedWorkspace.tsx) owns shared state, navigation and action review, and each [task view](../app/src/features/guided/workspace/tasks/index.ts) its body and footer.
  Its backend, [Guided](../backend/dazedtl/translation/guided.py), composes [action review and execution](../backend/dazedtl/translation/guided_actions.py), [run inspection](../backend/dazedtl/translation/guided_inspection.py), the [release form](../backend/dazedtl/translation/guided_release.py) and [context setup](../backend/dazedtl/translation/guided_context.py).
- Each workflow action is one row of the [action registry](../backend/dazedtl/actions.py), which says how it is reviewed and run and what History calls it; Guided, the worker and, through the generated contracts, the renderer read it.
- Every change to a game's files goes through the [game-write gateway](../backend/dazedtl/compatibility/game_write.py), whose docstring holds the rules, and each change is a [checkpoint](#checkpoints).
- Files and processes go through the [platform layer](../backend/dazedtl/system.py); see [Windows](#windows).

## Engine and resources

The engine ships inside this package: the [runtime locator](../backend/dazedtl/compatibility/runtime.py) selects it whatever the working directory, with no external fallback.
It was imported from `b91bede18fd2bbd5a9b99f1a866f061bc13865c1` with its [license](../backend/dazedtl/engine/LICENSE.md) and component notices.
The compatibility layer extends it only through declared [extension points](../backend/dazedtl/engine/util/extensions.py) and engine settings: mark an engine function as a point DazedTL extends instead of wrapping it from outside.
Its translation modules are the ones DazedTL's own flows run (`TRANSLATION_MODULE_SPECS` in [translation_task](../backend/dazedtl/engine/util/translation_task.py)): RPG Maker MV/MZ, which also translates VX Ace data, and Image Text; Assistant-led extracts and writes with Len's tools instead.
A saved run of a module retired since is refused when resumed, naming its engine, and sends nothing.
Saved manual runs record their engine's [version](../backend/dazedtl/engine/desktop/backend/manual.py) (`ENGINE_VERSIONS`); raise it when a change makes the engine build different requests from the same files, except RPG Maker MV/MZ, whose request changes are [frozen policies](#frozen-request-policies).

The base translation rules in [system.md](../backend/dazedtl/engine/data/skills/system.md), the prompt templates, field instructions, base glossary and SFX reference live in the engine's [data](../backend/dazedtl/engine/data) folder.
A workspace's `engine/shared-data` overrides them, and nothing is copied into profiles, so new defaults reach new preparations.
The base rules are a template on the run's languages ([prompt_pair](../backend/dazedtl/engine/util/prompt_pair.py)), and Japanese to English renders exactly as it did before languages became a setting, so its runs, estimates and caches stay current.
The base glossary, the SFX reference and the honorific rules apply to a Japanese source only.

### RPG Maker text blocks

[rpgmaker_blocks](../backend/dazedtl/engine/util/rpgmaker_blocks.py) is the one definition of how MV/MZ event commands form the text one window shows; translation, the fitter, Text QA, Assistant-led's writer and the playtest all read blocks there.
Writers lay text over a block's rows and never add or remove a command, so a saved game's place in an event stays valid.
Which comments players read comes from the plugins the game loads ([rpgmaker_markers](../backend/dazedtl/engine/util/rpgmaker_markers.py)).

## Guided runs and paid work

### Estimates and approval

- Each phase binds its estimate to source, scope, provider, pricing, guidance and layout; estimate workspaces are temporary and never enter history or supply translations.
- Paid work needs a matching estimate, whose inputs are checked again before a one-use approval submits it under the API lock.
- Approved work is saved before its worker starts, and its frozen request stays authoritative for recovery, never silently rebuilt.
- Navigation never submits work, approval alone never establishes success, and a cancelled late reply cannot open a review or start paid work; new remaining work and a Live resume, which pays for unfinished files without a new estimate, need their own review.
- Translate reopens the phase's latest estimate while it is current by the [freshness](../backend/dazedtl/engine/util/freshness.py) rule, so declining a review costs no second estimate.
- A saved figure is priced again only by rule: a model switch reprices an estimate whose requests stay the same ([repricing](../backend/dazedtl/translation/repricing.py)), and a pricing fix names the routes it changes in `ROUTE_PRICE_RULES` in [provider_costs](../backend/dazedtl/engine/util/provider_costs.py), so figures on those routes are priced again from their counts or read outdated, while a fix to a Live price changes no saved figure; an approved run keeps the price it was approved at.
- A change to how output tokens are counted outdates estimates: `RUN_VERSION` or `ESTIMATE_VERSION` for Guided, `OUTPUT_RULES_VERSION` in [estimate_prices](../backend/dazedtl/compatibility/estimate_prices.py) for Assistant-led.
- Both methods price by one rule: estimates and quotes through [estimate_prices](../backend/dazedtl/compatibility/estimate_prices.py), and each Live response's usage, cache reads and writes included, through `usage_cost` in [provider_costs](../backend/dazedtl/engine/util/provider_costs.py).
  Batch cache hits are best effort, so a Batch whose provider caches prompts is priced as a range.
- Claude estimates use [Claude's own token count](../backend/dazedtl/engine/util/claude_tokens.py), since Anthropic's tokenizer makes more tokens of the same text than the encoder other estimates use.
  The estimate worker has no credential or network, so [estimate_pricing](../backend/dazedtl/compatibility/estimate_pricing.py) counts in a separate process.
- Nameplates may hold any label, so the names step never assumes a character identity.
  Its names translate Live before the file Batch, join the glossary marked `Unverified nameplate` and stay reusable whatever happens to the Batch ([speaker_results](../backend/dazedtl/compatibility/speaker_results.py)).
- A task is complete only by verified per-file progress across runs ([translationTaskComplete](../app/src/features/guided/translationView.ts)); active, partial or outdated work can't establish it.
- Monitoring and new runs never share a worker, and an RPG Maker estimate parses all its files in one worker process, since a process per file took seconds each on Windows.

### Whole-game estimate

[full_estimate.py](../backend/dazedtl/translation/full_estimate.py) runs Context's Cost estimate as a tool operation, never a run, so no approval or paid work can follow from it; its [worker](../backend/dazedtl/compatibility/full_estimate.py) builds each task's plan with a Translate estimate's helpers, so the figures match.

### Frozen request policies

Each new API run freezes its request policies before estimating.
A policy joins the estimate's identity and applies to Live and Batch alike, and a run frozen without it keeps its original requests.
The policies are constants in [preferences.py](../backend/dazedtl/settings/preferences.py), each documented there, except the clarification retry and state calls, which define their `POLICY` beside their code.
Among them:

| Policy | Rule |
| --- | --- |
| [Clarification retry](../backend/dazedtl/translation/refusals.py) | A refused request is sent once more, naming the fictional source; refused again, its lines stay untranslated. |
| Page packing ([request_packing](../backend/dazedtl/engine/util/request_packing.py)) | Small scenes share a request, since each request repeats the whole system prompt; Assistant-led's organize packs by the same rule. |
| [Run stop](../backend/dazedtl/compatibility/run_stops.py) | A provider error that every later request would get too ends the run, and its request isn't sent again. |
| [Resend](../backend/dazedtl/compatibility/resends.py) | A failed Live request is sent again only when no try of it may have been billed and another may pass (`resendable` in [transmission](../backend/dazedtl/compatibility/transmission.py)). |
| [State calls](../backend/dazedtl/compatibility/state_requests.py) | Compatible state calls are coalesced, keeping the native field writer. |

- Every engine module ends a file by one rule in [translation_task](../backend/dazedtl/engine/util/translation_task.py): a parser error stops it before it writes, the output is written once and whole, and its receipt has one format.
- A module never writes its run's `files/`, which hold the run's frozen inputs.
- A module writes a reply list by the one reply rule (`reply_to_write` in [translation](../backend/dazedtl/engine/util/translation.py)): a list of the wrong length writes nothing.
- A run's evidence ledger counts each billed item once, however its file ends ([run_evidence](../backend/dazedtl/compatibility/run_evidence.py), [batch_validation](../backend/dazedtl/compatibility/batch_validation.py)), and a file's tokens, cost and time come from it by one rule (`run_receipts` in translation_task).

### Batch execution and recovery

- Uncertain work is never sent again automatically, and a restart needs no second approval for an unchanged approved queue.
- A Batch approval binds the whole frozen queue and plan; only its worker advances it, and the [Batch monitor](../backend/dazedtl/translation/batch_monitor.py) restarts that worker after an interruption and collects results whatever screen is open.
- Explicit stops, provider cancellations, newer overlapping runs, changed scope and uncertain submissions stop automatic continuation.
- A request reads as never sent only with evidence from the [submission journal](../backend/dazedtl/compatibility/batch_continuation.py) or the [transport observer](../backend/dazedtl/compatibility/transmission.py), and a Live request reads failed rather than uncertain only when no try of it can have been billed.
- Results are consumed automatically only with a durable fetched marker and receipts for every prepared request.
- Results download only once every Batch of a run has ended, so its files fill in together; [`batch_waiting_message`](../backend/dazedtl/compatibility/process_view.py) is the one waiting line, and it says so with the requests done and failed out of those sent.
- The [OpenAI Batch window](../backend/dazedtl/compatibility/batch_window.py) gives each job at most a quarter of the token allowance, and both methods' jobs on one connection share it.
- Provider reads and downloads run outside the API lock.

### Evidence and validation

- Evidence, such as response bodies, refusals, request mappings and [validation receipts](../backend/dazedtl/compatibility/batch_validation.py), is kept apart from accepted values and saved before validation; missing evidence never establishes success or billed usage.
- A refusal never enters game dialogue ([refusals](../backend/dazedtl/translation/refusals.py)), and [saved_refusals](../backend/dazedtl/translation/saved_refusals.py) puts the source back where older runs saved a refusal note.
- The response check reads source-language text left in a reply by the same rule as file status (`source_left` in [source_text](../backend/dazedtl/engine/util/source_text.py)), and every step that reshapes a reply follows the target's script ([target_text](../backend/dazedtl/engine/util/target_text.py)).
- A reply whose only faults are some lines' content is saved except for those lines, which the next Translate sends again; wrong lines, placeholders or control codes reject it whole.

### Result reuse

Workers save each validated value under a source identity independent of model, prompt and chunk size.
A later run reuses it line by line, never as a whole-file skip, while the source and file versions match and the value still passes the response check; the newest compatible run wins.

### Run history and inspection

- Run history is the single run list, and its [run inspector](../app/src/features/guided/RunInspector.tsx) owns cancellation, queue controls, collection recovery and reapplication, reading the observer's receipts without a polling loop of its own.
- Approved runs stay in History, failed and cancelled ones included.
- Saved run status never vetoes a new translation: overlapping submitted or uncertain requests get a duplicate-charge advisory in the cost review, and automatic recovery never resends them.
- Request rows, payloads and logs stay out of observations and browser preferences.

### File status and Lines

Database files and Maps & events read each file's status and Lines from the file itself through [file_lines](../backend/dazedtl/translation/file_lines.py), whatever runs wrote it.
[rpgmaker_scope](../backend/dazedtl/engine/util/rpgmaker_scope.py) defines what an event file holds, and a line is left while it holds source-language text by the engine's own rule ([source_text](../backend/dazedtl/engine/util/source_text.py)), read against the value's `_original` or the game's recorded original file ([original_values](../backend/dazedtl/engine/util/original_values.py)) in the game's language pair ([languages](../backend/dazedtl/engine/util/languages.py)), or while it holds a refusal note.
The engine probe ([engine_runtime](../tests/fixtures/engine_runtime.py)) checks that the engine sends exactly the lines this counts as left, so the two can't drift apart.

### Apply and release

- Apply is a full overwrite that binds the frozen candidates by hash; it never settles receipts or establishes completion, and Reapply uses a run's verified output, never the latest working copy.
- One [fitter](../backend/dazedtl/engine/util/rpgmaker_rewrap.py) fits text for translation, Apply, Assistant-led's writes, Text QA and new Line widths, so no writer's text needs fitting by the next.
  Widths count cells by one rule (`cells` in [dazedwrap](../backend/dazedtl/engine/util/dazedwrap.py)), and lines break as the target's script writes them.
- New Line widths queue a [fit_text](../backend/dazedtl/translation/text_fit.py) publication that rewraps only lines that no longer fit, so hand layout that fits stays.
- Release freezes the runtime scope and commits through a one-use preview, and a clean game ZIP holds only that scope and files a saved snapshot holds, so a translator's notes stay out.
- Both methods release by the same [release](../backend/dazedtl/translation/release.py) rules: `release.current` reads a ZIP Outdated once a later checkpoint changes a file it would ship, and `release.public_version` is the one rule for GameUpdate's config in a ZIP.
  Assistant-led's patch checks are each a `PackageRefusal`, whose message is the assistant's next step and whose reason is the user's (`unfinished` in [service](../backend/dazedtl/translation/service.py)).
  The assistant's `operation package` refuses with the first, while the user's patch needs only Git setup with its runtime manifest and GameUpdate's repository: its review lists the unmet checks and builds anyway, as Guided's patch waits for no QA, and the build refuses a check its review didn't list.
- A VX Ace game ZIP's name must be ASCII: its Game.exe fails as "RGSS301.dll File corrupted" from a Japanese-named folder on English Windows.
- Writing the GameUpdate config never marks saved work Outdated, and outside RPG Maker, GameUpdate installs only for engines whose patch layouts were checked (`GAMEUPDATE_ENGINES` in [translation](../backend/dazedtl/compatibility/translation.py)).
- Assistant-led's preparation installs or takes out GameUpdate, Forge and TL Inspector as the project's options choose, and `setup_mismatch` in [translation](../backend/dazedtl/compatibility/translation.py) is the one rule that holds the assistant's patch, and warns in the user's, while the game's GameUpdate or Forge differs from them.

## Plugins and images

The [plugin service](../backend/dazedtl/plugins/service.py) owns investigation, working copies and checked publication for MV/MZ plugins and VX Ace's Ruby scripts.

- The assistant decides which plugin text players see, so Apply to game writes every checked file in one click.
- An Acorn AST inventory binds reports to exact source bytes without running plugin code, and the [Ruby reader](../backend/dazedtl/plugins/ruby.py) gives Ace's scripts the same inventory in Python.
- Lookup values, code keys, expressions, structure and control tokens stay protected and are never asked about; original text comes from the game's recorded original files.
- Labels Text QA finds squeezed come to Plugin files, since QA never writes plugin files, and each shortened label is confirmed on screen in the [game window](../backend/dazedtl/engine/util/rpgmaker_window/launcher.cjs).

The [image service](../backend/dazedtl/images/service.py) owns the inventory, selection, discovery, editing contracts, reports and application receipts that Guided and Image Manager share.

- The selection moves through the four steps of [imageFlow](../app/src/features/images/imageFlow.ts), and the service alone decides whether the images are investigated.
- Lettered sound effects are flavor, often hundreds per game, so an image with nothing else stays out of the list; detector misses alone never certify an image has no text.
- Every image an assistant changes needs a [recipe](../backend/dazedtl/images/recipes.py), and reports pass the same [validation](../backend/dazedtl/images/validation.py) as the assistant's validator; only the user accepts an image the assistant can't prove, and the app never runs a recipe's command.
- A [family](../backend/dazedtl/images/families.py) member is reviewed by the crop that differs from an examined sibling, so look-alike CG frames aren't paid for again.
- Revision notes are the user's per-image intent, so they save with the selection through `images_update` until a report answers them; each answered note, apply and restore then joins the image's capped revision history on its inventory row.
- Apply freezes the batch in a one-use preview, and Restore originals reads each selected image from the game's [original files](#original-game-files) instead of undoing apply checkpoints, which would bring back an earlier translation after a reapply and images the user didn't select.
- The [background solver](../backend/dazedtl/images/background.py) and the [image text editor](../backend/dazedtl/images/editor.py) use only offline resources, never a hosted fallback or model download.

Plugin and image progress belongs to the project that saved it: work from a copied game or another profile is reported by [foreign_work](../backend/dazedtl/foreign_work.py) and used only when the user chooses.

## UI and state decisions

### UX principles

Strive for [Nielsen's ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) when designing and reviewing this tool.
Make current state and the next useful action visible; use translation tasks and familiar language; offer clear exits and recovery; keep shared controls consistent; prevent scope and spending mistakes; make prerequisites visible instead of requiring memory; support both guided and experienced use; prioritize relevant actions; give errors a practical recovery path; and put concise help beside the task that needs it.
Use these principles to evaluate real workflows, rather than adding extra panels or confirmation steps to satisfy a checklist.
Routine reversible actions start on one click; a review stays only where the user approves cost, scope or a consequential change, and execution checks and duplicate-submission guards always stay.

Give each idea one name and keep it everywhere:

- Apply only means writing into the game; settings are saved or used.
- Checkpoints are the game's Git commits, one per change, which the user views, goes back to, undoes or copies; a game update merges a new official version into them.
- Line widths are the per-line character limits DazedTL wraps translated text to, with the rows a message window shows.
- Assistant-led is the UI name of the method built on Len's game-translation skills; code and records keep the `len` identifier.

Assistant-led's starting prompt runs the whole method without the user: it asks only for spending approval, a missing API connection, denied access or a decision no source evidence settles, and a check it cannot make stays pending instead of stopping the run.

### Visual design

The app ships [Inter](../app/src/assets/fonts/Inter-OFL.txt), so text widths and wrapping match on every platform; system fonts only supply scripts it lacks, Japanese faces first.
The rounded [Fredoka](../app/src/assets/fonts/Fredoka-OFL.txt) sets only the wordmark and page titles, through `--font-family-display`.
Every literal font size, weight, color, spacing step and radius lives in [tokens.css](../app/src/styles/tokens.css); [styles.mjs](../scripts/styles.mjs) rejects literals in any other stylesheet, so a new value starts as a named token.

- Type: five sizes (page titles; task, dialog and section titles; body text and row titles; secondary text and controls; captions) and three weights: headings and emphasis semibold, row titles medium, everything else regular.
- Headings: one per region, never a stack before content; headings in a dialog body sit a step below its title.
- Measure: paragraphs and notes stop at `--measure`, about 72 characters; tables, editors, grids and row labels keep their layout's width.
- Forms: labels stack above controls, except Settings and dialog forms, which use a label column; related checkboxes share one label in [CheckGroup](../app/src/ui/FieldRow.tsx); choices and short values are at most 24rem wide, and paths, search and free text use the wide variant.
- Controls: buttons, single-line inputs and selects share `--control-height` and `--control-radius`, so a field and its button line up.
  Pick a control by its choice: a checkbox for on or off, [SegmentedControl](../app/src/ui/SegmentedControl.tsx) for one of a few short options, [OptionCards](../app/src/ui/OptionCards.tsx) for one of a few that each need a line of explanation, a select for longer lists, and [ComboBox](../app/src/ui/ComboBox.tsx) when a typed value is allowed.
- Spacing: 4px `--space-*` steps, 8 inside a group, 16 between rows and 24 to 32 between sections; `--space-half` only nudges small marks, and 1px only aligns borders.
- Corners and depth: `--control-radius` for controls and small marks, `--panel-radius` for panels, `--dialog-radius` for dialogs; popovers and menus share `--shadow-popover`, and dialogs use `--shadow-dialog` over `--color-backdrop`.
- Color: teal-tinted neutrals with a cyan-green accent, and done marks in leaf green, so finished never looks selected.
  Accent marks interactive text, focus and what is current; accent strong sits under white text on the one primary button; accent subtle marks selected surfaces.
  Green, amber and red mark status, always with text or an icon; image canvases keep their own `--color-canvas-*` and `--color-mark-*`, since they draw over game images.
- Brand: the dazed cat appears only as the teal window icon and its accent outline in the top bar and the Project page's welcome row.
  The outline is [CatMark](../app/src/ui/CatMark.tsx): its sparkles twinkle and X eyes turn for one loop when it appears and while it is pointed at, never otherwise, and it stays still under reduced motion.
- Icons appear in navigation, on actions that leave the app, on menus and disclosures, and on Add; other actions are text only.
- Footers start with Back and end with Continue; the task's own action sits just left of Continue and is the primary until the task is done, then Continue is, so each screen has one primary.
- Placement: a task's main action lives in its footer, rows hold supporting actions, and headers hold task-wide views or settings.
  A task's purpose is its one-line TaskHeader description; consequences sit in the review dialog of the action they qualify, a precondition beside its action, background in a help popover beside what it explains, and status stays visible.
- Small windows: below 1100px wide the sidebar becomes a rail of icons over short labels, and windows 720px tall or shorter compact the top bar and footers.

### Workflow and shared presentation

Use the flat, compact [Settings](../app/src/features/settings/Settings.tsx) and [Project page](../app/src/features/project/ProjectPage.tsx) as page examples.

#### Places and surfaces

The sidebar has three places: the Project page holds everything about the game, Translation holds the work, and Settings holds the app.
Beside them, the [Guide](../app/src/features/guide/Guide.tsx) shows the user guide from the install, through the main process so it opens while Python is busy or down; help that a guide section covers links to it with Learn more ([guideSections](../app/src/ui/guideSections.ts)).
It draws the guide with marked's lexer and its own React components, so no HTML from the file reaches the page, and anchors come from github-slugger, so they match the forge's.
Each game has one translation method, chosen in [MethodDialog](../app/src/features/project/MethodDialog.tsx); changing it keeps the other methods' work, and the Project page's Status, History and Checkpoints tabs serve all three.
Screens use four kinds of surface, each with one job:

- A page is somewhere you work or browse, reached from the sidebar and kept when you leave and return.
- A tab is another view of the same thing, and switching never loses your place or drafts.
- A dialog holds one decision or one focused edit and ends in an explicit choice; it opens no other dialog except a detail view that returns to it, and a dialog that leads to a review closes before the review opens.
- A menu is a short list of choices that closes when you pick one.

New pages start from one of three templates: the task page (stepper, task tabs, TaskHeader, panels, work area, footer), the editor page that Settings, the Project page and [Assistant-led](../app/src/features/translation/Translation.tsx) share (header, tabs, a scrolling body and footer per tab), and the decision dialog (the decision as its title, what will happen, explicit footer choices).
Editing footers sit outside scrolling content.
Sheets and inspectors close with the header's one close button; decisions such as spending reviews, resyncs and Apply have no close button and end with explicit footer choices.
Reserve cards for content that needs a distinct container; tables, editors and the image grid stay unboxed.

#### Layout

Every stylesheet loads through [index.css](../app/src/styles/index.css) in a cascade layer (tokens, base, shared UI, shell layout, then features), so a feature's rules override shared primitives without raising specificity; keep selectors simple.
Layouts stay readable and usable from small laptop screens to 4K monitors and TVs: reflow from the window size and display scaling, keep actions reachable on small displays, and use large ones without stretching or gaps.
Every page centers one content column, `--content-width`; a workspace that needs every pixel, the Images task, is a wide [PageLayout](../app/src/ui/PageLayout.tsx), whose body alone spans the window.
Frame rows (headers, stage strip, task tabs, messages, scrolling bodies and footers) span the window and pad their content to that column, and rows that don't scroll reserve the body's scrollbar gutter, so edges match across screens.
Editors and file lists keep a minimum height and the body scrolls instead; tabs of different heights stack in [StackedTabPanels](../app/src/ui/Tabs.tsx), so switching keeps the size and each tab's place while hidden panels start no requests; rows grow with feedback rather than fixing heights or clipping.
Default to compact, task-focused layouts; never hide an overstuffed layout behind disclosures, and shorten long text with an explicit expand action.
Review a layout change by resizing it where it reflows, with long labels and paths, in its idle, pending, success and error states; check alignment, text-to-action gaps, clipping, overflow and redundant status text, and report any state left unverified.

#### Shared components

Compose shared primitives with design tokens, and fix a reusable layout defect in the primitive instead of compensating per screen with per-button widths, fixed text heights or clipped feedback:
[ActionList and ActionRow](../app/src/ui/ActionList.tsx) for repeated label and action rows, [Menu](../app/src/ui/Menu.tsx) for action lists that open from a button, [ComboBox](../app/src/ui/ComboBox.tsx) for editable suggestions, [Modal](../app/src/ui/Modal.tsx) with [DialogHeader and DialogBody](../app/src/ui/Dialog.tsx) for dialogs, [JobStatus](../app/src/ui/JobStatus.tsx) for operation summaries, [StatusMark](../app/src/ui/StatusMark.tsx) and [StatusIcon](../app/src/ui/StatusIcon.tsx) for status, [Notice](../app/src/ui/Notice.tsx) for inline notes, [StatusPanel](../app/src/ui/StatusPanel.tsx) for work that is not the user's own, [FileName](../app/src/ui/FileName.tsx), [PathInput](../app/src/ui/PathInput.tsx) and [PathText](../app/src/ui/PathText.tsx) for names and paths, and [ActionSlot](../app/src/ui/ActionSlot.tsx) for a tab's footer action.
Shortcuts come from [useShortcut](../app/src/state/useShortcut.ts), scoped to the visible screen and the top dialog; nothing that spends, applies or packages gets a shortcut.

#### Status and feedback

- Work items say where they stand in one vocabulary, the display states in [displayStatus.ts](../app/src/ui/displayStatus.ts), each with one mark; each feature maps its own states there and keeps its specific reason in the item's detail.
- Waiting means the work is with an assistant, never that the app is running something; Done is finished work that never writes into the game; Outdated marks a saved result whose basis changed before it went into the game, while edits after it was applied leave it as it was.
- Action controls pair the shared pending button and status feedback with `useAction`'s guarded action key; a result or disabled reason sits beside its own control, so buttons keep their place.
- A confirmation with nothing left to do, such as a copy, fades away by itself in [FadingNote](../app/src/ui/FadingNote.tsx); failures and results the user still acts on stay.
- Each status shows once: a heading that shows an action's outcome names that action's key, and while it says Done or Applied the control leaves out its success; pending work and failures always stay beside the control.
  [FeedbackOwners](../app/src/ui/FeedbackOwners.tsx) links the two, and saved operations carry their action identity, so feedback stays beside the right control after navigation or restart.
- Keep failures beside their action or in the run or file inspector; never collect historical errors into page-wide reminders or counters.
- Saved results, logs, frozen scope and record IDs belong in the inspector's Technical view; routine views also leave out zero counters, finished progress bars and repeated explanations.
- A control presents a saved artifact as available only after checking it on disk.

#### Guided stages and tasks

- Translation follows the Qt GUI's task order through [workflow.ts](../app/src/features/guided/workflow.ts), in five stages: Set up, Context, Translate, Check and Release.
- A stage holds the tasks that share its purpose, so no stage exists only to host one optional workspace; optional work never holds up the next step, and a stage of optional tasks only is done once opened with every required task before it done.
- Tabs and Continue keep drafts and allow navigation regardless of completion; they never save review receipts or complete skipped tasks.
- Routine setup steps and local estimates make and consume their preview right after the click, so each keeps its checks and receipts; paid work, runtime replacement and file resync keep their review.
- Each task applies its own work and shows what it hasn't applied, with no cross-task reminder list; applied Translate output has no restore of its own, since its checkpoint is the undo.
- A Translate task is done only once every file it covers reads Applied or Done, which `translationTaskComplete` in [translationView.ts](../app/src/features/guided/translationView.ts) decides for every place that shows it.

#### Working copies

Working copies are seeded from the game's current bytes and kept across navigation, estimates and restarts; the selected phase files bind each new run and application preview.
A game update records new originals, so the files it changed read Outdated until Resync brings in their new text ([guided_inputs.py](../backend/dazedtl/translation/guided_inputs.py)), and Apply refuses them until then.
Resync archives a file's working copy, staged outputs and cache, and advances its version first, so earlier runs can't overwrite it even if Resync is interrupted.

#### Assistant tasks

- Every task that hands work to an assistant shows the shared [AssistantTask](../app/src/ui/AssistantTask.tsx) panel, which reports only copied instructions or saved findings, never a process inferred from a click.
- The [assistant task registry](../backend/dazedtl/translation/assistant_tasks.py) records each copy's handoff, features keep their own requests, reports and validation, and [assistantTasks.ts](../app/src/features/assistant/assistantTasks.ts) derives one display state per task for the Project page, the top bar and the feature's panel.
- Saved findings stay a record of the source they inspected, and a saved scan that is no longer current says why.
- Speaker findings ([speaker_setup.py](../backend/dazedtl/translation/speaker_setup.py)) enable only confirmed rules on verified sources, from a scan without credentials or network that never translates names.
- Event text findings ([event_text](../backend/dazedtl/translation/event_text.py)) bind to the selected files, original data, plugin dependencies and the parser's registry, and text no handler captures gets the game's own [custom patterns](../backend/dazedtl/engine/util/custom_patterns.py) instead of an engine change.

#### Assistant-led

- Its API run panel holds the assistant's estimate, and its button is the only approval: the project helper resumes only runs the user approved there, and a newer estimate replaces the one waiting ([newest_estimate](../backend/dazedtl/translation/jobs.py)).
- New games start on API Batch, since the assistant's own plan pays for every turn.
- In both methods, a Batch the connection can't run shows and runs as Live, with the reason beside the choice ([runnable_mode](../backend/dazedtl/settings/execution.py)), and the saved choice stays.
- Start over is one checkpoint back to the original game's current version, so the attempt stays in Git history; what Git doesn't keep moves to `.dazedtl/archived`, settings and skills stay, the glossary and notes stay unless the user lets them go, and only the user can start it.

#### Manual and translation files

- [Manual](../app/src/features/translation/ManualTranslation.tsx) runs on Assistant-led's machinery: its loaded file becomes the units organize packs, the API run panel's button is the only approval, and History lists its runs; the [translation contract](translation-contract.md#translation-files) says what its runs leave out.
- Each method's pages show only its current runs (`own` in `job_views`): not another method's, one an import superseded, or a finished Manual run of an earlier file.
- A [translation file](../backend/dazedtl/translation/exchange.py) exports and imports a project's lines in every method through one line set per method; an import never writes the game itself, only accepted results or Guided's working copies, which Apply publishes.

#### Publication

A [text publication](../backend/dazedtl/translation/publication.py) freezes reviewed destinations, then fits, checks and writes the whole batch in one game write; its receipt names the checkpoint it made and keeps no copy of what it replaced, since Git does.
History's Undo of a batch undoes its checkpoint, by the Checkpoints tab's rule.
A batch that stopped midway, or failed after writing all its files, made no checkpoint; since part of it may be in the game, every Guided task raises a notice, and its Restore puts its files back as its starting checkpoint had them.

#### Text QA

- Text QA and the release playtest are optional and never prerequisites for navigation or Release.
- One [QA policy](../backend/dazedtl/engine/data/skills/rpgmaker_translation_qa.md) makes the task README, every reviewer brief and the copied handoff, so they can't disagree; the [design](text-qa-redesign.md) holds the goals, decisions and evidence.
- The [QA engine](../backend/dazedtl/engine/util/qa/__init__.py) owns stages, bundles, workers, declines, observations, findings and the review ledger; content is never classified or excluded in advance.
- Its [preflight](../backend/dazedtl/engine/util/rpgmaker_qa_preflight.py) reports Japanese never translated, with its [reach](../backend/dazedtl/engine/util/rpgmaker_qa_reach.py), but QA neither reviews it nor blocks on it; in Assistant-led, the helper's `qa` status sends what players may see, the census counts and the assistant didn't decline back to the assistant's extraction and injection, and the rest stays reported, so that step always ends (`untranslated` in [text_qa](../backend/dazedtl/translation/text_qa.py)).
- On an engine Text QA can't read, Assistant-led gets its text-only checks through the helper's `qa --check` ([result_checks](../backend/dazedtl/translation/result_checks.py)).
- Corrections pass the engine's correction and regression checks on disposable copies and are fitted by the one fitter, so findings store what the game gets; one that reads as a refusal fails them.
- Each [lint](../backend/dazedtl/engine/util/rpgmaker_qa_lint.py) family names the targets it checks, and only families whose fix was always right in released games apply automatically; the evidence is beside `AUTOMATIC` there.
- Release QA applies its finished findings without asking, as one `qa_apply` batch History can undo; apply waits only for questions, and no QA command writes game files itself or pushes.
- Preparing QA captures the interface screens in the [game window](../backend/dazedtl/engine/util/rpgmaker_window/launcher.cjs), offscreen, read-only and offline, so nothing reaches the game's saves; since QA never writes plugin files, squeezed plugin text goes to Plugin files in Guided and to the assistant through the helper's `qa` status in Assistant-led.
- The playtest's [checks](../backend/dazedtl/engine/util/playtest/checks.py) and [tour](../backend/dazedtl/engine/util/playtest/harness/main.cjs) report problems as observations of a `playtest` worker, so findings never make another task ([its design](text-qa-redesign.md#release-playtest)).
- The assistant's [fixes plugin](../backend/dazedtl/engine/util/playtest/fixes.py) is written only after a play with it passes, and joins every patch's manifest.

### Navigation and responsiveness

- Project identity, execution mode and the visible screen are separate; registry upgrades keep IDs, job references, selections and recovery data.
- `useApplication` supplies shared state through one observer, which owns response order and refresh scheduling; features add no polling loops of their own.
- The shared [navigation state](../app/src/app/navigation.ts) owns the visible screen and each project's workflow views apart from backend observations, so a background read can't move the user back.
  Route screens and Guided locations through `useApplication`'s navigation methods, and keep feature-local view choices in their own UI state.
- Workflow tasks, document tabs and event-code views are small browser-profile preferences, written before the view changes, holding no game text, drafts or authority.
- Task Options panels configure their task in place, reusing the settings controls, and never act as menus to other phases; cross-task navigation stays in the phase and task controls.
- Switching to an already-loaded view with clean drafts needs no Python request and waits for no snapshot.
  A navigation or observer change proves this in the [observer tests](../tests/application.test.ts): the switch completes while a backend read stalls, sends no navigation or refresh request and survives a late snapshot, while draft recovery, project ownership and execution guards still hold.
- Keep usable page data across revisits where ownership and invalidation allow, and scope any load and its feedback to the feature that needs it; [App](../app/src/app/App.tsx) and the [Guided workspace hook](../app/src/features/guided/workspace/useGuidedWorkspace.tsx) are examples.
- Automatic refreshes yield to the next operation in a chained action, so saving and then navigating inserts no discarded read.
- Give `useAction` the application as its `observer` when its completion needs updated state, and keep `application.refresh` for an intentional re-read, never on every button.
- Views that show their own replies before the next observation use [`useObserved`](../app/src/state/useObserved.ts): a newer snapshot replaces a reply, except while unsaved edits or actions build on it.
- An open project stays observed while no worker runs, so assistant reports appear; a failed read is retried after a growing delay, and a disconnection invalidates pending reads.

Observations stay small:

- Snapshot work uses bounded summaries or cached derivations with explicit invalidation; source, artifact and spending checks stay at execution or inspection, and cached display state never authorizes paid work or publication.
- A poll does no whole-game parsing, starts no process per file and rebuilds no request history; a digest cache it reads must hold the whole working set ([ObservedFiles](../backend/dazedtl/translation/files.py), [Digests](../backend/dazedtl/engine/util/freshness.py), bounded [process summaries](../backend/dazedtl/compatibility/process_view.py)).
- Requests run one at a time behind the lock every snapshot needs, so work that takes seconds on a big game starts an operation worker.
- Values derived from a game's files live in the project's [derived store](../backend/dazedtl/translation/derived.py), keyed on their inputs and a version per kind, so they outlast a restart.
- Measure nontrivial additions with representative generated data.

Drafts and actions:

- `useAction` guards duplicate submissions, and `useDraft` serializes recovery writes and explicit saves; drafts stay dirty until committed, and leave guards flush them before navigation and close.
  Autosaving editors, such as Image Manager, save every write instead.
- Mutations that change snapshot-backed state keep the default `refresh` in their [method contract](../backend/dazedtl/api/contracts/methods.py), so a remounted editor can't recover an older draft.
- Never retry writes automatically, since some actions submit paid work.
- Error boundaries keep render failures from navigation and the observer, and retries flush draft guards before remounting; Electron owns the crash dialog and reloads only on the user's choice, keeping the Python process and its jobs.
- Plugins is bundled with the other screens, so rebuilding the app can't remove a chunk an open window needs.

### Persistence and settings

- Project-format changes raise `SCHEMA_VERSION` with consecutive upgrades in [projects/store.py](../backend/dazedtl/projects/store.py); [`read_versioned_json`](../backend/dazedtl/storage.py) validates the result, backs up the original and replaces it atomically.
- Whether saved work is current has one rule, in [freshness](../backend/dazedtl/engine/util/freshness.py): it is keyed on its inputs and an explicit version, never on hashes of source files, so an update alone never outdates it.
- A Text QA task is keyed on what it reviews and `QA_RULES_VERSION` in [qa/schema](../backend/dazedtl/engine/util/qa/schema.py), raised only when saved reviews become wrong or unreadable; the [previous-release QA check](development.md#previous-release-qa-check) fails when a change needs it.
  A prepared task stays current through QA's own Apply and Undo ([compatibility/text](../backend/dazedtl/compatibility/text.py)).
- Workflow options live in the game's `.dazedtl/len-method/workflow.json`, its original files in its Git repository and its guidance in its own files ([paths](../backend/dazedtl/engine/util/paths.py)); the app profile holds connections, recoverable drafts, run plans and receipts.
- Opening and selecting a project publish ownership only after it is saved, and removing a game from the recent list hides its record, so its runs keep their owner.
- The project registry is the only record of where a project's game is ([location](../backend/dazedtl/projects/location.py)): the game folder names its project in a marker Git never commits, so a moved game keeps its project and a copy opens a new one.
  Other records find the game through the registry, and no saved key names the game folder: estimates, Text QA context and bindings name the game's files relative to it, so a move changes one record, outdates nothing and needs no new approval.
- Diagnostics record only fixed metadata and code locations, never messages, payloads or raw stderr; a [watchdog](../backend/dazedtl/watchdog.py) records hangs, workers report through the [diagnostics](../backend/dazedtl/diagnostics.py) hooks, and the report names the checkout revision.
  **Report a problem** copies a Discord-sized summary of the same records with the open game's name, engine and mode, which the renderer passes in.
  **Share a fix** copies a [task](../backend/dazedtl/engine/data/skills/share_fix.md) for the user's assistant that opens with the same facts and asks for a report on a fix the assistant made in the game, with no secrets or long game text.
- Connections and preferences share one atomic record, the workspace's `settings/settings.json`, with the languages new games start in.
  A game records its pair in `.dazedtl/settings.json` at Set up, and every run freezes it ([language_pair](../backend/dazedtl/settings/language_pair.py)); a pair whose languages share a script is refused, since letters couldn't tell translated text from text left.
- A Japanese source names no source in frozen settings, the translation cache, Batch keys or the census, so work saved before languages became a setting stays current.
- Saved secrets never enter renderer responses or recovery drafts, and model drafts bind to connection IDs.
  A preferences draft counts as unsaved only while it differs from the saved values ([store](../backend/dazedtl/settings/store.py)), since a draft Settings can't save or revert must not block switching models.
- The public preference schema is [preferences.py](../backend/dazedtl/settings/preferences.py); legacy engine values are kept privately and materialized only before engine actions.
- Provider presets declare their transport protocol apart from their identity; existing connections and frozen runs keep their identity and route, and runs find credentials by the connection's name, so removing a connection strands its unfinished runs.
- A request to OpenCode's gateway names a session, one per stream of requests sent one after another so each keeps its prompt prefix cached, and DazedTL as its User-Agent, by one rule (`gateway_headers` in [providers](../backend/dazedtl/settings/providers.py)); every sender puts them on its client, never in a request's params, which Batch files, saved plans and Inspect keep.
- Settings that change requests, such as an OpenRouter host, token budgets, thinking effort ([effort](../backend/dazedtl/settings/effort.py)) and rates, freeze into each new plan through the [request adapter](../backend/dazedtl/compatibility/request_parameters.py) and [worker adapter](../backend/dazedtl/compatibility/worker_policy.py), so a settings change can't redirect or reprice a resumed run.
  One reader in [execution](../backend/dazedtl/settings/execution.py) builds them, as the `configuration` estimates and Assistant-led runs freeze and as the `request_policy` a Guided or image run's engine freezes.
  A resume passes only its saved plan to `prepare_engine` in [settings/store.py](../backend/dazedtl/settings/store.py), which skips the new-run checks, such as whether the active connection runs Batch, and checks only the run's own connection.
- Prices are looked up outside the lock only when preparing, reviewing or approving work; snapshots use prices already looked up ([model_defaults](../backend/dazedtl/compatibility/model_defaults.py)).

### Notifications

[WorkAlerts](../app/src/app/workAlerts.ts) reads every observation outside rendering, so a background window still notices; its docstring says which work calls the user back.
The main process shows desktop notifications only while the window is unfocused, and [posts each alert to ntfy](../app/electron/phone.cjs) whatever the focus; the renderer reaches no network, and the main process sends only to ntfy.
On Windows a notification needs the app's ID on its Start menu shortcut, so the main process gives the launcher's shortcut that ID and removes the `Electron.lnk` Electron writes.

## API changes

The [Python contracts](../backend/dazedtl/api/contracts) define every method's parameters, reply shape and flags once.
Change a method there, in its handler and in [client.ts](../app/src/api/client.ts), then run `node scripts/contracts.mjs`, which generates the renderer's [contracts.ts](../app/src/api/contracts.ts) and the [protocol manifest](../backend/dazedtl/api/protocol.json) that Electron and the project helper read; the build fails while either is stale.
The protocol version is a hash of the contracts, so any change rejects a stale renderer or helper before mutations run.

- Replies pass through the [public views](../backend/dazedtl/api/views.py), which keep legacy records behind that boundary.
- Contracts are closed: declare what the renderer and helper may read and drop the rest; only records the backend keeps for its own recovery stay open beyond their documented keys.
- The [contract test](../tests/test_api_contracts.py) checks every handler against its contract, and launching with `DAZEDTL_CHECK_CONTRACTS=1` validates every request and reply while developing.
- Methods refresh the workspace snapshot by default; allow close-time operations only when needed to finish saving or reading.
- Contract checks are a development aid; domain operations still validate input and check ownership.

## Translation execution and the agent boundary

- The starting prompt drives `scripts/project.py` against an authenticated loopback endpoint in the running backend; its connection descriptor is profile-local, permission-restricted and removed on shutdown, and its token never enters a handoff.
- Agent operations use the same locked dispatch and ownership checks as Electron; the helper has no settings or general shell endpoint, and no route to what only the user starts, such as going back, undoing, saving a copy or Start over.
- The app controls its workers; an assistant's activity is read from saved artifacts and never shown as an app-owned process.
- A progress report is checked before the app records QA's evidence or checkpoints, so a refused one changes nothing, and the app keeps the last report it published in the project's records, out of the game where the assistant writes, so later refreshes never build on one the assistant sent or edited ([progress_report](../backend/dazedtl/translation/progress_report.py)).
- On Windows every copied task opens with a [note](../backend/dazedtl/translation/helper_command.py) naming DazedTL's own Python with `-X utf8` and its bundled Git, since a fresh Windows has neither and Python's pipes can't carry Japanese in the ANSI code page; its commands are PowerShell, and the note says how to run them from Git Bash or WSL ([shell_note](../backend/dazedtl/system.py)).

Guided and Assistant-led differ in who extracts, drives and reviews the work, never in the quality of the text.
A rule that shapes translated text, such as the prompt and its context, output checks and lint, fitting, [word spacing](../backend/dazedtl/engine/util/word_spacing.py) and Text QA, has one definition both methods call, and an improvement to either reaches the other in the same change or as a queued follow-up.
Assistant-led brings each such rule that needs no engine parser to its other engines too.

Assistant-led runs:

- A compiled plan freezes sources, context, field constraints, provider parameters, rates and connection, and the run's record and approval bind the plan file's exact bytes ([plan_file](../backend/dazedtl/translation/plan_file.py)).
- Organize builds plans from engine-neutral units that Len's extractor saves, so parsing and injection stay in Len's per-engine tools and the assistant never rewrites the game's text; a census of the recorded prepared game decides scope, so the extractor can't narrow it.
- Units carry no assistant notes: per-line notes come from the tool, such as a battle message's users ([battle_users](../backend/dazedtl/engine/util/battle_users.py)), and name codes show as the actor's name through [actor_names](../backend/dazedtl/engine/util/actor_names.py), as in Guided.
- Organize and compile run in an operation worker ([run_compiler](../backend/dazedtl/translation/run_compiler.py)), and the run's worker compiles every request again and compares before it sends.
- A line keeps its accepted translation while its unit ID and source stay the same ([unit_results](../backend/dazedtl/translation/unit_results.py)), so organizing again quotes only the lines without one.
- A request lists a partly translated scene's other stretches with the lines before them and their translation ([request_packing](../backend/dazedtl/engine/util/request_packing.py)), and a Live run's later part of a split scene carries the English the run delivered for the lines it quotes, added at send time (`delivered_block` in [prompt_pair](../backend/dazedtl/engine/util/prompt_pair.py)); a Batch builds every request before any result exists, so its parts carry the source alone.
- Submission intent is saved before provider calls and raw receipts before acceptance, and an uncertain submission blocks overlapping work.
- Approval receipts bind the project, plan and quote with a profile-local signature; a saved boolean alone can't authorize a worker.
- Workers hold per-run locks and stop once their owning process is gone; closing asks them to stop at a checkpoint, then ends them with their processes, and each keeps its temporary files in a [folder of its own](../backend/dazedtl/translation/jobs.py) that the app removes.

Games and Git:

- Git baselines gate new translation work, and the game-write gateway refuses writes while the checkout is off the translation branch or mid-operation; [checkout_issue](../backend/dazedtl/translation/operations.py) names the problem for the refusal and the [GameWarnings](../app/src/ui/Notice.tsx) notice, and work DazedTL starts as it polls waits for Git instead ([checkout_waiting](../backend/dazedtl/translation/guided.py)).
- Start over is the one game writer the [write check](../tests/game_writes.py) lets past the gateway, since it must run whatever state the checkout is in.
- DazedTL's own runtime files join every manifest and every checkpoint of its writes ([dazedtl_files](../backend/dazedtl/engine/util/len_patch_scope.py)), because a patch without them once gave players a `plugins.js` loading a plugin the patch lacked; TL Inspector is the one tool no patch carries ([installer](../backend/dazedtl/engine/util/tl_inspector/installer.py)).
- Official game updates are staged and merged by [version_update](../backend/dazedtl/engine/util/version_update), whose modules explain why each kind of file merges as it does, and a complete release is staged prepared as the game's current version was ([rpgmaker_prepare_release](../backend/dazedtl/compatibility/translation.py)).

VX Ace:

- Preparation runs in Python on every platform: [util/ace](../backend/dazedtl/engine/util/ace) ports RV2JSON 1.2.1 and RPGMakerDecrypter's archive reading, and [the Ace fixture](../tests/fixtures/ace/regenerate.py) records RV2JSON's own output, so tests need neither Ruby nor real games.
- RGSS3 reads only the archive while `Game.rgss3a` exists, so Set up keeps it in `.dazedtl/ace`, and patches carry it rebuilt from the game's current files.
- The game reads only Data, so the gateway packs what a write changed in `ace_json` ([pack_ace](../backend/dazedtl/compatibility/guided.py)), and Release requires a current packing.
- `ace_json` is the translation's text, so checkpoints let it into the translation branch and restore it, but patch ZIPs and players' downloads leave it out ([is_game_tool_file](../backend/dazedtl/engine/util/paths.py)).
- A game update converts a complete release or a new archive the same way, and an Ace release reads as a complete game only when it also ships Game.exe and the RGSS library ([release_layout](../backend/dazedtl/engine/util/version_update/release_layout.py)).
- Ace data is translated by the MV/MZ engine with its `VXACE` option ([phase_workflow](../backend/dazedtl/engine/desktop/backend/workflow.py)), so frozen plans carry it.

## Windows

Each Windows rule lives where code can't skip it, because the bugs it prevents never show on Linux.

- Python touches files and starts processes through the [platform layer](../backend/dazedtl/system.py), whose docstring lists its rules; Ruff and [platform_calls](../scripts/platform_calls.py) reject the calls it replaces everywhere else, the engine included ([checks](development.md#checks)).
- `held_open` makes a file look held by another process, as Windows refuses to replace, rename, delete or open one then, and a test drives each kind of writer and reader through it.
- [paths](../scripts/paths.mjs) rejects tracked names that differ only in case and paths over the Windows length budget.
- Code on a poll path starts no process: Defender makes each start slow, and one user's jobs froze for 17 seconds while every snapshot ran 22 Git commands.
  Checkpoints ask Git only what they can't know ([checkpoint_commits](../backend/dazedtl/compatibility/checkpoint_commits.py)), and [test_git_launches](../tests/test_git_launches.py) holds each checkpoint operation to its count of Git processes.
- A worker's parent on Windows is the virtual environment's launcher stub, so ownership checks use [launched_by](../backend/dazedtl/translation/ownership.py), never `os.getppid`.
- [Shortcuts](../scripts/shortcuts.mjs) are written through IShellLinkW, since WScript.Shell passes their text through the ANSI code page.

## Checkpoints

The game folder's Git repository is the one record of a translation: every change DazedTL makes to a game whose Git is set up is one commit on the translation branch, a checkpoint, made by [checkpoint_commits](../backend/dazedtl/compatibility/checkpoint_commits.py), whose docstring holds the rules.

- The gateway records one when the outermost write succeeds, so no flow commits by hand or asks the user to, and a failed write commits nothing; a write whose files changed but whose checkpoint failed is committed by the next write, under its own name.
- Changes made outside DazedTL get a checkpoint of their own before each write and game update, so nothing waits for a clean worktree; the checkout refusals stay.
- A checkpoint's subject is its stage and a summary from the action [registry](../backend/dazedtl/actions.py), with `DazedTL-Action`, `DazedTL-Stage` and `DazedTL-Version` trailers, so checkpoints group by stage without a saved record.
- One save the user asks for is one write and one checkpoint.
- The translation branch is patch-scoped: a file outside the patch is the original game's, which its [original files](#original-game-files) hold, so restoring never deletes it.
- Commits to one repository take turns through a lock in its Git folder, and each write registers its files, so two writes at once commit their own.
- Assistant-led writes the game with its own tools too, so the app commits what waits in the patch at each progress report and when a run ends ([progress_report](../backend/dazedtl/translation/progress_report.py)).
- The Checkpoints tab reads the branch's log ([checkpoint_history](../backend/dazedtl/compatibility/checkpoint_history.py)) when it opens and after a write, never on a poll.
- Going back and undoing write through the gateway, so each is a checkpoint, within the current game version; [blocker](../backend/dazedtl/compatibility/checkpoint_history.py) is the one rule for which later checkpoint an undo waits on, which History and Plugin files read too.
- Each feature's apply names its checkpoint, so undoing it or going back past it takes out what the features applied there ([checkpoint_records](../backend/dazedtl/translation/checkpoint_records.py)).
- Save a copy writes the game as of a checkpoint into a new folder, and Electron opens only folders the backend returns.

## Original game files

A game's original files are kept in its own repository under the private ref `refs/dazedtl/originals` ([original_files](../backend/dazedtl/compatibility/original_files.py), whose docstring holds the kinds of record).
The `original` branch can't hold them: it holds only the files a patch can change and is published with the translation, while a private ref is never pushed.

- The game is recorded before DazedTL first changes a file the record holds; recording a big game takes minutes, so it runs in a worker of its own ([original_record](../backend/dazedtl/compatibility/original_record.py)), and a write that would change a recorded file waits, or refuses with [Feedback](../app/src/ui/Feedback.tsx) showing the record's progress.
- Set up records the prepared game, and a game update records the release it stages; a record counts only once the update's commit names it in a `DazedTL-Prepared` trailer, so a cancelled update leaves the current record, and readers take the record the branch names ([prepared_record](../backend/dazedtl/compatibility/original_files.py)).
- Nothing is removed from the ref, and a record is never rewritten.
- [originals](../backend/dazedtl/translation/originals.py) is where every reader gets them, from plugin lookups and release file lists to Restore originals and Start over.
- DazedTL takes no backups now; a project set up before reads the backups in its game's `.dazedtl/backups/v2` store through [backups](../backend/dazedtl/translation/backups.py), and scripts/backups.py recovers from one without the app profile.

## Distribution and updates

Users download the repository as a ZIP and run a START launcher; there is no installer or build pipeline.

- The launchers only fetch the Node pinned in [runtimes.lock](../scripts/runtimes.lock), checked against its published checksum, then hand over to [start.mjs](../scripts/start.mjs); [setup.mjs](../scripts/setup.mjs) installs the pinned Python the same way, creates `.venv` and installs the hash-locked packages and Electron.
- [zip.mjs](../scripts/zip.mjs) unpacks Electron's binary, because Electron's own installer needs the Visual C++ runtime, which a fresh Windows lacks.
- Each step records its inputs in `.runtime/state.json` and reruns only when they change, so an update or a moved folder repairs the install on the next start.
  A folder two systems share holds one system's install at a time: setup parks the other's in `.runtime/parked/<system>`.
- Windows ships no Git, so setup installs the pinned portable MinGit, and the launcher puts its Node and that Git first on the app's `PATH`.
- Ubuntu's AppArmor rules block the Chromium sandbox of unregistered binaries, so the launcher stops with a one-time profile command instead of letting Electron exit silently.

A release is a `v` tag on every mirror in [mirrors.json](../release/mirrors.json), whose commit carries `release/manifest.json`, the SHA-256 of every tracked file, signed with Ed25519 in `release/manifest.sig`.

- [update.mjs](../scripts/update.mjs) lists tags through each mirror's Git ref advertisement and takes the newest version any reachable mirror has.
- GitGud answers requests without one of the headers its Cloudflare rule looks for with a challenge, so every request to a GitLab host carries `X-Gitlab-Token`, whose value GitLab ignores: `mirrorHeaders` here, [gitgud](../backend/dazedtl/engine/util/gitgud.py) for the maintainer tools, and GameUpdate's scripts; never a real token, which would ship to every install.
- Players' [GameUpdate](../backend/dazedtl/engine/gameupdate/gameupdate) takes a patch from the forge's API and archive, and when either fails, from a shallow `git fetch` of the branch packed with `git archive`, so its files match the forge's archive.
  Before any Git, a plain GET of the ref advertisement reads the branch, which also settles a missing or private repository and "already up to date"; the in-game check reads it the same way.
  Git's requests are Git's own, never dressed as a browser's or another client's.
  Before copying anything, a patch that holds Git LFS pointer files, which Git and some forges' archives bring in place of LFS files, is refused, and so on Windows is one whose paths would not fit in the game's folder, so a patch is never applied halfway.
  On Windows without Git, `patch.ps1` downloads the MinGit pinned here and unpacks it in the game's `gameupdate/mingit` once its SHA-256 matches, downloading it again once if it fails to run; `runtimes.mjs` writes that pin into the script, so it works wherever a patch puts it, and `gameupdate_local` in [project_preparation](../backend/dazedtl/engine/util/project_preparation.py) keeps it and the run's lock out of patches.
  A game gets a new GameUpdate only when DazedTL copies it in again (Recreate GameUpdate files, or Assistant-led's preparation) and the translation is pushed.
- An archive is accepted only when the signature verifies with a key in the installed `release/keys` and its files match the manifest exactly, so a compromised or stale mirror can withhold releases but never alter one; [release.mjs](../scripts/release.mjs) proves each tag against its own `git archive` before pushing.
- The [update controller](../app/electron/updates.cjs) runs the updater in a child process, so verifying never blocks the window.
- The launcher applies a staged update before setup and before anything loads the files it replaces, as a journaled, backed-up swap that finishes after a crash and restores on failure, then hands over to the new launcher; START.bat stays one line ([bootstrap.ps1](../scripts/bootstrap.ps1) says why).
- Files outside the manifest, such as `.venv`, `.runtime` and downloaded models, are never touched, and Git checkouts are left to Git.
- The app writes nothing beside the files a manifest lists: it compiles its Python into the profile, and the commands it hands assistants do too ([platform layer](../backend/dazedtl/system.py)).
- Every tracked path stays within the Windows path budget of 185 characters ([paths.mjs](../scripts/paths.mjs)).
