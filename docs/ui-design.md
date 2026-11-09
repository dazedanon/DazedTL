# UI design

How DazedTL's screens look and behave, for anyone building or reviewing one; [architecture](architecture.md) holds the code ownership and state rules behind them.

## UX principles

Strive for [Nielsen's ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) when designing and reviewing this tool.
Make current state and the next useful action visible; use translation tasks and familiar language; offer clear exits and recovery; keep shared controls consistent; prevent scope and spending mistakes; make prerequisites visible instead of requiring memory; support both guided and experienced use; prioritize relevant actions; give errors a practical recovery path; and put concise help beside the task that needs it.
Use these principles to evaluate real workflows, rather than adding extra panels or confirmation steps to satisfy a checklist.
Routine reversible actions start on one click; a review stays only where the user approves cost, scope or a consequential change, and execution checks and duplicate-submission guards always stay.

Give each idea one name and keep it everywhere:

- Apply only means writing into the game; settings are saved or used.
- Checkpoints are the game's Git commits, one per change, which the user views, goes back to, undoes or copies; a game update merges a new official version into them.
- Line widths are the per-line character limits DazedTL wraps translated text to, with the rows a message window shows.
- Assistant-led is the UI name of the method built on Len's game-translation skills; code and records keep the `len` identifier.

## Rules for every screen

These come from the design guidance of Nielsen Norman Group, Apple, IBM Carbon, GitHub Primer, Atlassian, GOV.UK and Microsoft Fluent, cut to what a screenshot can be checked against.
They exist because screens built one fix at a time collect repeated status, extra buttons and disabled controls that nobody planned, such as a footer that once showed Stop, a "Running" spinner and a disabled Estimate cost with its own spinner for one run.

Status and progress:

1. One state, one indicator: a running operation shows one status, a mark with words, in one place, never a spinner in a button beside a status beside a notice ([Primer](https://primer.style/product/ui-patterns/loading/), [NN/g](https://www.nngroup.com/articles/indicators-validations-notifications/)).
2. Long work takes over its own control: while it runs, the slot that started it shows the status and Stop, and no disabled copy of the start button stays; a button shows its own spinner only for a short wait that can't be stopped ([NN/g](https://www.nngroup.com/articles/state-switch-buttons/), [Carbon](https://carbondesignsystem.com/components/inline-loading/usage/)).
3. Say what is happening, such as "Translating 6 lines with 3 models", with a count once the total is known, never a bare "Running" ([Apple](https://developer.apple.com/design/human-interface-guidelines/progress-indicators), [NN/g](https://www.nngroup.com/articles/progress-indicators/)).
4. Match the wait: under a second, nothing; up to about ten seconds, a spinner with words; longer, counted progress with Stop beside it ([NN/g](https://www.nngroup.com/articles/response-times-3-important-limits/)).

Actions:

5. One primary, and it is the next step: what the user most likely does next in this state; running the same thing again is secondary ([Carbon](https://carbondesignsystem.com/components/button/usage/), [GOV.UK](https://design-system.service.gov.uk/components/button/)).
6. Hide what waits on the next step: a control usable only after the primary's step stays hidden until then, and one disabled for any other reason says why beside it, never in a tooltip alone ([Atlassian](https://atlassian.design/components/button/usage), [Smashing](https://www.smashingmagazine.com/2024/05/hidden-vs-disabled-ux/)).
7. Two or three actions per footer; an action about one part of the screen sits next to it, such as a column's menu in its header ([NN/g](https://www.nngroup.com/articles/gestalt-proximity/)).

One fact, one place:

8. Each fact shows once: a name, a price, a reason, a run's state; when a column says a model was left out, the footer doesn't say it again ([GOV.UK](https://design-system.service.gov.uk/components/notification-banner/), [NN/g](https://www.nngroup.com/articles/minimize-cognitive-load/)).
9. Red means it failed; something the user can fix before a run, such as a missing price, is a warning that names the fix ([NN/g](https://www.nngroup.com/articles/error-message-guidelines/)).
10. Labels earn their words: buttons start with a verb, take two to four words in sentence case, and neighbors don't repeat each other ([NN/g](https://www.nngroup.com/articles/first-2-words-a-signal-for-scanning/), [GOV.UK](https://www.gov.uk/service-manual/design/writing-for-user-interfaces)).
11. Compared items are columns and their lines are rows; every column gets the same treatment, and a missing or failed cell says why ([NN/g](https://www.nngroup.com/articles/comparison-tables/)).
12. Review every state, not the happy one, as below ([NN/g](https://www.nngroup.com/articles/how-to-conduct-a-heuristic-evaluation/)).

## Visual design

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

## Places and surfaces

Use the flat, compact [Settings](../app/src/features/settings/Settings.tsx) and [Project page](../app/src/features/project/ProjectPage.tsx) as page examples.
The sidebar has four places: the Project page holds everything about the game, Translation holds the work, Compare tries models on a few of its lines, and Settings holds the app.
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

## Layout

Every stylesheet loads through [index.css](../app/src/styles/index.css) in a cascade layer (tokens, base, shared UI, shell layout, then features), so a feature's rules override shared primitives without raising specificity; keep selectors simple.
Layouts stay readable and usable from small laptop screens to 4K monitors and TVs: reflow from the window size and display scaling, keep actions reachable on small displays, and use large ones without stretching or gaps.
Every page centers one content column, `--content-width`; a workspace that needs every pixel, the Images task, is a wide [PageLayout](../app/src/ui/PageLayout.tsx), whose body alone spans the window.
Frame rows (headers, stage strip, task tabs, messages, scrolling bodies and footers) span the window and pad their content to that column, and rows that don't scroll reserve the body's scrollbar gutter, so edges match across screens.
Editors and file lists keep a minimum height and the body scrolls instead; tabs of different heights stack in [StackedTabPanels](../app/src/ui/Tabs.tsx), so switching keeps the size and each tab's place while hidden panels start no requests; rows grow with feedback rather than fixing heights or clipping.
Default to compact, task-focused layouts; never hide an overstuffed layout behind disclosures, and shorten long text with an explicit expand action.
Review every layout change as [Reviewing a screen](#reviewing-a-screen) says.

## Shared components

Compose shared primitives with design tokens, and fix a reusable layout defect in the primitive instead of compensating per screen with per-button widths, fixed text heights or clipped feedback:
[ActionList and ActionRow](../app/src/ui/ActionList.tsx) for repeated label and action rows, [Menu](../app/src/ui/Menu.tsx) for action lists that open from a button, [ComboBox](../app/src/ui/ComboBox.tsx) for editable suggestions, [Modal](../app/src/ui/Modal.tsx) with [DialogHeader and DialogBody](../app/src/ui/Dialog.tsx) for dialogs, [JobStatus](../app/src/ui/JobStatus.tsx) for operation summaries, [StatusMark](../app/src/ui/StatusMark.tsx) and [StatusIcon](../app/src/ui/StatusIcon.tsx) for status, [Notice](../app/src/ui/Notice.tsx) for inline notes, [StatusPanel](../app/src/ui/StatusPanel.tsx) for work that is not the user's own, [FileName](../app/src/ui/FileName.tsx), [PathInput](../app/src/ui/PathInput.tsx) and [PathText](../app/src/ui/PathText.tsx) for names and paths, and [ActionSlot](../app/src/ui/ActionSlot.tsx) for a tab's footer action.
Shortcuts come from [useShortcut](../app/src/state/useShortcut.ts), scoped to the visible screen and the top dialog; nothing that spends, applies or packages gets a shortcut.

## Status and feedback

- Work items say where they stand in one vocabulary, the display states in [displayStatus.ts](../app/src/ui/displayStatus.ts), each with one mark; each feature maps its own states there and keeps its specific reason in the item's detail.
- Waiting means the work is with an assistant, never that the app is running something; Done is finished work that never writes into the game; Outdated marks a saved result whose basis changed before it went into the game, while edits after it was applied leave it as it was.
- Action controls pair the shared pending button and status feedback with `useAction`'s guarded action key; a result or disabled reason sits beside its own control, so buttons keep their place.
- A confirmation with nothing left to do, such as a copy, fades away in [FadingNote](../app/src/ui/FadingNote.tsx); failures and results the user still acts on stay.
- Each status shows once: a heading that shows an action's outcome names that action's key, and while it says Done or Applied the control leaves out its success; pending work and failures always stay beside the control.
  [FeedbackOwners](../app/src/ui/FeedbackOwners.tsx) links the two, and saved operations carry their action identity, so feedback stays beside the right control after navigation or restart.
- Keep failures beside their action or in the run or file inspector; never collect historical errors into page-wide reminders or counters.
- Saved results, logs, frozen scope and record IDs belong in the inspector's Technical view; routine views leave out zero counters, finished progress bars and repeated explanations.
- A control presents a saved artifact as available only after checking it on disk.

## Reviewing a screen

Screenshot the changed screen at the window size it opens with and at the smallest, 900 by 520, with long labels and paths, in each state it can reach: empty, ready, starting, running from this screen and from elsewhere, stopping, partial failure, failure, done, and any mode such as hidden names.
On each screenshot check, in order:

1. One focal point, and it is the next step.
2. At most one primary button.
3. One indicator per running thing, beside it.
4. Every disabled control says why on screen, or should be hidden.
5. Each fact once: names, prices, reasons, states.
6. No word repeated across neighbors, and no "Label: value" where the value explains itself.
7. Each control next to what it changes.
8. Red only for failure.
9. Alignment, text-to-action gaps, clipping and overflow.

Report each finding with its screenshot and the rule it breaks, and any state left unverified.
