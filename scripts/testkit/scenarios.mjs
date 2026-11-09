// The ready-made scenarios scripts/scenario.mjs builds. Each names its steps
// as a user takes them; a scenario that continues another starts with its
// steps.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { python } from "../dependencies.mjs";
import { Page, until } from "./cdp.mjs";
import {
  contentFolder,
  gameName,
  makeGame,
  makeRelease,
  release,
} from "./games.mjs";
import { model, recordedRequests, translated } from "./provider.mjs";
import {
  chooseFile,
  chooseFolder,
  connect,
  openGame,
  setUp,
  translateTask,
  applyTask,
  buildPatch,
  playtestPanel,
} from "./journey.mjs";
import { entries } from "../zip.mjs";

/**
 * The scenario's Python running `args` with the options the app hands an
 * assistant: UTF-8 mode and the profile's bytecode cache, so nothing compiles
 * into the checkout (backend/dazedtl/system.py).
 */
export const pythonCommand = (state, ...args) => [
  state.env?.DAZEDTL_PYTHON || python,
  "-X",
  "utf8",
  "-X",
  `pycache_prefix=${path.join(state.profile, "python-cache")}`,
  ...args,
];

/** Runs a pythonCommand and returns its output. */
const runPython = ([file, ...args]) =>
  execFileSync(file, args, {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });

/** Runs a Python script of the scenario's checkout, as an assistant's shell does. */
const run = (state, script, ...args) =>
  runPython(pythonCommand(state, path.join(state.root, script), ...args));

/** The project helper command for `project`, as an assistant's task runs it. */
export const helperCommand = (state, project) =>
  pythonCommand(
    state,
    path.join(state.root, "scripts/project.py"),
    "--workspace",
    path.join(state.profile, "workspace"),
    "--project",
    project,
  );

/** The scripted assistant answering the Plugin files task `request`, as a
 * pythonCommand. */
export const pluginAssistant = (state, project, request) =>
  pythonCommand(
    state,
    path.join(import.meta.dirname, "plugin_assistant.py"),
    request,
    "--game",
    state.game,
    "--helper-json",
    JSON.stringify(helperCommand(state, project)),
  );

/** Runs the project helper with `args` and reads its JSON reply. */
async function helper(page, state, ...args) {
  const project = (await page.call("workspace_snapshot")).application.project;
  return JSON.parse(runPython([...helperCommand(state, project.id), ...args]));
}

const open = [
  "Open the game with Guided steps",
  ({ page, state }) =>
    openGame(page, {
      root: state.root,
      inspect: state.app.inspect,
      game: state.game,
    }),
];
const setup = [
  ["Set up the game", ({ page }) => setUp(page)],
  [
    "Connect the stand-in provider",
    ({ page, state }) => connect(page, state.provider.url),
  ],
];
const translateAll = [
  [
    "Translate and apply the database",
    async ({ page }) => {
      await page.click("3Translate");
      await translateTask(page, "Database files", { failed: true });
      await applyTask(page, "Database files");
    },
  ],
  [
    "Translate and apply maps and events",
    async ({ page }) => {
      // Lines a variant has the stand-in refuse fail their run.
      await translateTask(page, "Maps & events", { failed: true });
      // A run that saved nothing new leaves Apply disabled, or away when it
      // saved nothing at all.
      const apply = /^Apply \(\d+\)$/;
      const next = await until("Maps & events' Apply to settle", async () => {
        if (await page.locate(apply)) return "apply";
        const text = await page.text();
        return (
          (!/Apply \(\d+\)/.test(text) ||
            text.includes("Nothing new to apply.")) &&
          "skip"
        );
      });
      if (next === "apply") await applyTask(page, "Maps & events");
    },
  ],
];

const plamoRequests = [
  "Check LM Studio got only requests PLaMo's template takes, each answered",
  ({ state }) => {
    const chats = recordedRequests(path.join(state.work, "provider")).filter(
      (item) =>
        item.method === "POST" &&
        item.route === "/chat/completions" &&
        /plamo-3-translate/.test(item.body?.model ?? ""),
    );
    if (!chats.length) throw new Error("No PLaMo request reached LM Studio.");
    const refused = chats.find((item) => item.status !== 200);
    if (refused)
      throw new Error(
        `PLaMo's template refused a request: ${JSON.stringify(refused.body).slice(0, 600)}`,
      );
    // One line a call: no JSON payload for it to translate as text.
    const json = chats.find((item) =>
      /"Line\d+"/.test(item.body.messages.at(-1).content),
    );
    if (json)
      throw new Error(
        `A call carried a JSON payload: ${json.body.messages.at(-1).content}`,
      );
    const actor = gameJson(state, "Actors.json")[1];
    if (!translated(actor.name) || !translated(actor.profile))
      throw new Error(
        `The database wasn't translated: ${actor.name}, ${actor.profile}`,
      );
  },
];

const narrowWidths = [
  "Narrow the Line widths and check the long message pages whole",
  async ({ page, state }) => {
    // Applied at the stock widths, the message is not laid out for 24.
    const applied = messageRows(state);
    if (cells(state, applied).every((width) => width <= 24))
      throw new Error("The message was already narrow before the widths.");
    const snapshot = await page.call("workspace_snapshot");
    const { id } = snapshot.application.project;
    const { preferences } = snapshot.guided;
    const values = {
      ...preferences.values,
      widths: { ...preferences.values.widths, width: 24, messageRows: 2 },
    };
    await page.call("guided_save_options", {
      project_id: id,
      revision: preferences.revision,
      values,
    });
    // Saving widths fits the applied text in the background.
    await until("the long message to page at the narrow widths", async () => {
      const rows = messageRows(state);
      return (
        rows.length > 2 &&
        cells(state, rows).every((width) => width <= 24) &&
        rows
      );
    });
    // Every character stays, the spaces between lines aside: English and
    // Japanese, which breaks between characters, alike.
    const shown = messageRows(state);
    const letters = (rows) => rows.join("").replace(/\s+/g, "");
    if (letters(shown) !== letters(applied))
      throw new Error(`The paged message lost text: ${shown.join(" | ")}`);
  },
];

/** The half-width cells each of `rows` takes, as the checkout's fitter counts
 * them (util/rpgmaker_rewrap visible_width): a full-width character, such as
 * kana, kanji or 。, takes two. */
const cells = (state, rows) =>
  JSON.parse(
    runPython(
      pythonCommand(
        state,
        "-c",
        "import json, sys; sys.path.insert(0, sys.argv[1]); " +
          "from util.rpgmaker_rewrap import visible_width; " +
          "print(json.dumps([visible_width(row) for row in json.loads(sys.argv[2])]))",
        path.join(state.root, "backend/dazedtl/engine"),
        JSON.stringify(rows),
      ),
    ),
  );

/** The text rows of the traveler's message commands in the game's Map001
 * (旅人, or Traveler in the English game), its commands' lines split apart;
 * a paged message holds empty rows that fill its last page. */
function messageRows(state) {
  const map = JSON.parse(
    fs.readFileSync(path.join(state.game, "data/Map001.json"), "utf8"),
  );
  const event = map.events.find(
    (item) => item?.name === "旅人" || item?.name === "Traveler",
  );
  return event.pages[0].list
    .filter((command) => command.code === 401)
    .flatMap((command) => command.parameters[0].split("\n"));
}

const playtest = [
  "Run the release playtest",
  async ({ page }) => {
    const project = (await page.call("workspace_snapshot")).application.project;
    await page.call("translation_playtest", {
      project_id: project.id,
      step: "run",
    });
    await page.idle(10 * 60_000);
    const summary = await page.call("translation_playtest", {
      project_id: project.id,
      step: "report",
    });
    console.log(`\n  Report: ${summary.report}`);
    const report = JSON.parse(fs.readFileSync(summary.report, "utf8"));
    for (const problem of report.problems)
      console.log(
        `  ${problem.kind} ${problem.check} -> fix ${problem.fix} ${problem.identity || problem.pointer || ""} ${JSON.stringify(problem.text || problem.texts?.[0]?.text || "")}`,
      );
    for (const stop of report.coverage?.stops || [])
      console.log(`  stop ${stop.id}: ${stop.status} ${stop.note || ""}`);
  },
];

/** Prepares Text QA through the project helper, reviews it with the
 * scripted reviewer, given `options` such as --corrections, and applies it;
 * returns what the reviewer reports. */
export async function reviewQa({ page, state }, ...options) {
  const prepared = await helper(page, state, "qa", "--prepare");
  // The reviewer of the checkout the app runs from, whose engine and QA
  // rules prepared the task.
  const reviewed = JSON.parse(
    run(
      state,
      "scripts/testkit/qa_reviewer.py",
      prepared.task,
      path.join(state.work, "qa-results"),
      ...options,
    ),
  );
  const applied = await helper(page, state, "qa", "--apply");
  if (!applied.applied)
    throw new Error(`Text QA did not apply: ${applied.message}`);
  await page.idle();
  return reviewed;
}

const qa = ["Review and apply Text QA as an assistant does", reviewQa];

const plugins = [
  "Translate and apply Plugin files as an assistant does",
  async ({ page, state }) => {
    const project = (await page.call("workspace_snapshot")).application.project;
    // What the task's Copy hands the assistant, without the clipboard.
    const task = await page.call("plugins_action", {
      project_id: project.id,
      action: "plugin_task",
    });
    if (!task.request)
      throw new Error(`Plugin files has no task: ${task.message}`);
    runPython(pluginAssistant(state, project.id, task.request));
    const applied = await page.call("plugins_action", {
      project_id: project.id,
      action: "apply",
    });
    if (applied.blocked?.length)
      throw new Error(
        `Plugin files left files out: ${JSON.stringify(applied.blocked)}`,
      );
    await page.idle();
  },
];

/**
 * What the app shows of the open project, with its game's folder named
 * `<game>` and keys in order, so a move compares equal. A finished
 * operation's result names the folder it worked in then, `was`.
 */
async function projectView(page, game, was = game) {
  const snapshot = await page.call("workspace_snapshot");
  const sorted = (value, result = false) =>
    Array.isArray(value)
      ? value.map((item) => sorted(item, result))
      : value && typeof value === "object"
        ? Object.fromEntries(
            Object.keys(value)
              .sort()
              .map((key) => [
                key,
                sorted(value[key], result || key === "result"),
              ]),
          )
        : result && typeof value === "string"
          ? value.replaceAll(was, game)
          : value;
  const { project } = snapshot.application;
  const text = JSON.stringify(
    sorted({
      project: { ...project, last_opened: undefined },
      guided: snapshot.guided,
      translation: snapshot.translation,
      plugins: snapshot.plugins,
      images: snapshot.images,
      foreign: [snapshot.pluginsForeign, snapshot.imagesForeign],
    }),
  );
  return text.replaceAll(JSON.stringify(game).slice(1, -1), "<game>");
}

/** Fails unless the project reads as before, keeping both views in the logs. */
function unchanged(state, before, after, what) {
  if (after === before) return;
  for (const [name, value] of Object.entries({ before, after }))
    fs.writeFileSync(path.join(state.work, `logs/${name}.json`), value);
  throw new Error(
    `${what} changed its project, History, tasks or saved progress; logs/before.json and logs/after.json differ.`,
  );
}

/** Whether the open project's game is `game` and its folder is there; the
 * page shortens a long path, such as under the home folder. */
async function opened(page, game) {
  const { project } = (await page.call("workspace_snapshot")).application;
  return project?.source === game && project.available;
}

/** Moves the game folder, as a user does outside the app. */
function moveGame(state, target) {
  const moving = state.game + ".moving";
  fs.renameSync(state.game, moving);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.renameSync(moving, target);
}

/**
 * Prepares Text QA again as an assistant does, and fails unless that goes on
 * with `task`, its README naming the game where it is now.
 */
async function sameQaTask(page, state, task) {
  const prepared = await helper(page, state, "qa", "--prepare");
  if (prepared.task !== task)
    throw new Error(
      `Preparing Text QA again made another task, ${prepared.task}, not ${task}.`,
    );
  const readme = fs.readFileSync(path.join(task, "README.md"), "utf8");
  if (!readme.includes(state.game))
    throw new Error(`The Text QA task's README does not name ${state.game}.`);
  await page.idle();
}

const moved = [
  [
    "Estimate the whole game's cost and prepare Text QA to review every line",
    async ({ page, state }) => {
      const project = (await page.call("workspace_snapshot")).application
        .project;
      await page.call("guided_full_estimate", { project_id: project.id });
      await page.idle();
      const { guided } = await page.call("workspace_snapshot");
      if (!guided.fullEstimate.current)
        throw new Error(
          `The whole-game estimate is not current: ${JSON.stringify(guided.fullEstimate)}`,
        );
      state.qaTask = (
        await helper(page, state, "qa", "--prepare", "--everything")
      ).task;
      await page.idle();
    },
  ],
  [
    "Move the game into a Game folder inside its own and open it there",
    async ({ page, state }) => {
      await page.click("Project");
      const before = await projectView(page, state.game);
      const game = path.join(state.game, "Game");
      moveGame(state, game);
      await page.waitText("Game folder unavailable");
      await page.waitText("Find game folder");
      await chooseFolder(
        { root: state.root, inspect: state.app.inspect },
        game,
      );
      // The project menu's button reads the project's name.
      const { project } = (await page.call("workspace_snapshot")).application;
      await page.click(project.name);
      await page.click("Open a game…");
      await until("the moved game to open", async () => opened(page, game));
      await page.idle();
      unchanged(
        state,
        before,
        await projectView(page, game, state.game),
        "Opening the moved game",
      );
      state.game = game;
      await sameQaTask(page, state, state.qaTask);
    },
  ],
  [
    "Rename that folder while Compare models shows and find it from the Project page",
    async ({ page, state }) => {
      const before = await projectView(page, state.game);
      const game = path.join(path.dirname(state.game), "Renamed");
      await page.click("Compare");
      await page.waitText("Single model");
      moveGame(state, game);
      // Compare models says the game is gone, as the other pages do.
      await page.waitText("Game folder unavailable");
      await page.click("Project");
      await chooseFolder(
        { root: state.root, inspect: state.app.inspect },
        game,
      );
      await page.click("Find game folder");
      await until("the found game to open", async () => opened(page, game));
      await page.idle();
      unchanged(
        state,
        before,
        await projectView(page, game, state.game),
        "Finding the game",
      );
      state.game = game;
      await sameQaTask(page, state, state.qaTask);
    },
  ],
];

/**
 * Restarts the app with what versions before 2.33.2 saved once the open
 * project's old folder, its game moved out, was opened again: that folder's
 * unrecognized engine over the project's own. `also` changes more of the
 * closed profile, given the registry, which this then saves.
 */
async function relabel(state, restart, also = () => {}) {
  const file = path.join(state.profile, "workspace/projects.json");
  return restart(() => {
    const registry = JSON.parse(fs.readFileSync(file, "utf8"));
    const project = registry.projects.find(
      (item) => item.id === registry.current_id,
    );
    project.engine = "Investigation pending";
    also(registry);
    fs.writeFileSync(file, JSON.stringify(registry, null, 2));
  });
}

const relabeled = [
  [
    "Move the game into a Game folder inside its own, relabeled, and open it there",
    async ({ page, state, restart }) => {
      // A restart forgets the History job selected, so the project reads as
      // it does after one.
      page = await restart(() => {});
      await page.click("Project");
      const before = await projectView(page, state.game);
      const game = path.join(state.game, "Game");
      moveGame(state, game);
      // That version then opened the Game folder as a new project, which
      // its marker named.
      const empty = "e".repeat(32);
      page = await relabel(state, restart, (registry) => {
        registry.projects.push({
          id: empty,
          name: "Game",
          source: game,
          engine: "MVMZ",
          method: "translation",
          backend_id: "",
          phase: "database",
        });
        fs.mkdirSync(path.join(game, ".git/dazedtl"), { recursive: true });
        fs.writeFileSync(
          path.join(game, ".git/dazedtl/project.json"),
          JSON.stringify({ version: 1, projectId: empty }) + "\n",
        );
      });
      await page.waitText("Game folder unavailable");
      await page.waitText("Find game folder");
      await chooseFolder(
        { root: state.root, inspect: state.app.inspect },
        game,
      );
      const { project } = (await page.call("workspace_snapshot")).application;
      await page.click(project.name);
      await page.click("Open a game…");
      await until("the moved game to open", async () => opened(page, game));
      await page.idle();
      unchanged(
        state,
        before,
        await projectView(page, game, state.game),
        "Opening the moved game",
      );
      state.game = game;
    },
  ],
  [
    "Rename that folder, leave an empty one, relabeled, and find it",
    async ({ page, state, restart }) => {
      const before = await projectView(page, state.game);
      const game = path.join(path.dirname(state.game), "Renamed");
      moveGame(state, game);
      fs.mkdirSync(state.game);
      page = await relabel(state, restart);
      await page.waitText("Game folder unavailable");
      await chooseFolder(
        { root: state.root, inspect: state.app.inspect },
        game,
      );
      await page.click("Find game folder");
      await until("the found game to open", async () => opened(page, game));
      await page.idle();
      unchanged(
        state,
        before,
        await projectView(page, game, state.game),
        "Finding the game",
      );
      state.game = game;
    },
  ],
];

const batch = [
  [
    "Connect the OpenAI preset, which reaches the stand-in",
    ({ page }) => connect(page, "", "openai"),
  ],
  [
    "Submit the database as a Batch the stand-in holds",
    async ({ page, state }) => {
      // Hold on top of the game variant's own mode, such as its replies.
      const modeFile = path.join(state.work, "provider/mode.json");
      const mode = fs.existsSync(modeFile)
        ? JSON.parse(fs.readFileSync(modeFile, "utf8"))
        : {};
      fs.writeFileSync(modeFile, JSON.stringify({ ...mode, hold: true }));
      await page.click("3Translate");
      await page.click("Database files");
      await page.click("Batch");
      await page.click("Translate");
      // An estimate that fails never enables Submit Batch; say why at once.
      const ready = await until(
        "an enabled Submit Batch control",
        async () =>
          ((await page.locate("Submit Batch")) && "ready") ||
          /Translation could not start\n+(.+)/.exec(await page.text())?.[1],
        5 * 60_000,
      );
      if (ready !== "ready")
        throw new Error(`The Batch could not start: ${ready}`);
      await page.click("Submit Batch");
      await page.waitText("Files fill in when");
    },
  ],
];

/** Runs the scripted Assistant-led assistant's `step`. */
async function assistant(page, state, step, ...args) {
  const project = (await page.call("workspace_snapshot")).application.project;
  return runPython(
    pythonCommand(
      state,
      path.join(import.meta.dirname, "assistant.py"),
      step,
      "--helper-json",
      JSON.stringify(helperCommand(state, project.id)),
      "--game",
      state.game,
      ...args,
    ),
  );
}

const assistantLed = [
  [
    "Open the game Assistant-led, the assistant translating",
    async ({ page, state }) => {
      await openGame(page, {
        root: state.root,
        inspect: state.app.inspect,
        game: state.game,
        method: "Assistant-led",
      });
      const project = (await page.call("workspace_snapshot")).application
        .project;
      const current = await page.call("translation_state", {
        project_id: project.id,
      });
      await page.call("translation_save", {
        project_id: project.id,
        revision: current.revision,
        values: { ...current.options, mode: "agent" },
      });
      // What copying the starting prompt records, without the clipboard.
      await page.call("translation_prepare", { project_id: project.id });
    },
  ],
  [
    "The assistant sets up the game",
    ({ page, state }) => assistant(page, state, "setup"),
  ],
  [
    "The assistant organizes the text and translates its first request",
    async ({ page, state }) => {
      await assistant(page, state, "organize");
      const run = JSON.parse(
        await assistant(page, state, "translate", "--requests", "1"),
      );
      console.log(`\n  Run ${run.id}: ${run.status}, ${run.message || ""}`);
    },
  ],
];

/** Runs the Manual project's own tools (manual_tools.py), as its user does. */
const manualTools = (state, ...args) =>
  runPython(
    pythonCommand(
      state,
      path.join(import.meta.dirname, "manual_tools.py"),
      ...args,
      "--game",
      state.game,
    ),
  );

/** The open project's latest translation run. */
async function latestRun(page) {
  const project_id = (await page.call("workspace_snapshot")).application.project
    .id;
  return (await page.call("translation_state", { project_id })).jobs.find(
    (job) => job.kind === "translation",
  );
}

const manualLed = [
  [
    "Open the game Manual and connect the stand-in provider",
    async ({ page, state }) => {
      await openGame(page, {
        root: state.root,
        inspect: state.app.inspect,
        game: state.game,
        method: "Manual",
      });
      await connect(page, state.provider.url);
    },
  ],
  [
    "Text saves an example file, your own extractor writes the game's text into a file, and Text loads it",
    async ({ page, state }) => {
      const example = path.join(state.work, "example.json");
      await chooseFile(
        { root: state.root, inspect: state.app.inspect },
        example,
      );
      await page.click("Save example…");
      await page.waitText("Example saved.");
      if (!JSON.parse(fs.readFileSync(example, "utf8")).lines.length)
        throw new Error("The example file holds no lines.");
      const file = path.join(state.work, "extracted.json");
      manualTools(state, "extract", "--out", file);
      await chooseFile({ root: state.root, inspect: state.app.inspect }, file);
      await page.click("Load text file…");
      await page.waitText("Loaded ");
      await page.shot(path.join(state.work, "logs", "manual-text.png"));
    },
  ],
  [
    "Progress estimates the lines, and the approved Live run, paused between requests and resumed, translates them",
    async ({ page, state }) => {
      await page.click("Progress");
      await page.click("Estimate cost");
      await page.waitText("Nothing is sent until you approve this estimate.");
      await page.shot(path.join(state.work, "logs", "manual-estimate.png"));
      // Each answer waits, so the run can pause between its requests.
      const modeFile = path.join(state.work, "provider/mode.json");
      const mode = fs.existsSync(modeFile)
        ? JSON.parse(fs.readFileSync(modeFile, "utf8"))
        : {};
      fs.writeFileSync(modeFile, JSON.stringify({ ...mode, delay: 1500 }));
      await page.click("Approve and start Live");
      await page.click("Pause at the next safe point");
      await until(
        "the run to pause",
        async () => (await latestRun(page))?.status === "stopped",
        60_000,
      );
      await page.waitText(
        "Resume the run first, so its lines aren't sent twice.",
      );
      await page.shot(path.join(state.work, "logs", "manual-paused.png"));
      fs.writeFileSync(modeFile, JSON.stringify(mode));
      await page.click("Resume");
      const run = await until(
        "the Live run to end",
        async () => {
          const job = await latestRun(page);
          return job?.approved &&
            ["complete", "failed", "uncertain"].includes(job.status)
            ? job
            : null;
        },
        5 * 60_000,
      );
      if (run.status !== "complete")
        throw new Error(`Run ${run.id}: ${run.status}, ${run.message}`);
      await page.waitText("lines saved");
      await page.shot(path.join(state.work, "logs", "manual-progress.png"));
    },
  ],
  [
    "Export the translations, and your own injector writes them into the game",
    async ({ page, state }) => {
      const file = path.join(state.work, "translated.json");
      await chooseFile({ root: state.root, inspect: state.app.inspect }, file);
      await page.click("Export translations…");
      await page.waitText("Saved ");
      const exported = JSON.parse(fs.readFileSync(file, "utf8"));
      const left = exported.lines.filter((line) => !line.translation);
      if (left.length)
        throw new Error(`The export leaves ${left.length} lines untranslated.`);
      manualTools(state, "inject", "--file", file);
      const data = path.join(contentFolder(state.variants, state.game), "data");
      const map = fs.readFileSync(path.join(data, "Map001.json"), "utf8");
      if (!map.includes("Tested"))
        throw new Error("The injector wrote no translation into Map001.json.");
    },
  ],
  [
    "The Project page imports a translation edited by hand, after reviewing it",
    async ({ page, state }) => {
      const exported = JSON.parse(
        fs.readFileSync(path.join(state.work, "translated.json"), "utf8"),
      );
      exported.lines[0].translation = "Edited by hand.";
      const file = path.join(state.work, "edited.json");
      fs.writeFileSync(file, JSON.stringify(exported));
      await page.click("Project");
      await page.click("Export/Import");
      await chooseFile({ root: state.root, inspect: state.app.inspect }, file);
      await page.click("Import…");
      await page.waitText("Import translations?");
      await page.shot(path.join(state.work, "logs", "manual-import.png"));
      await page.click("Import 1 translation");
      await page.waitText("Imported 1 translation");
      const again = path.join(state.work, "again.json");
      const project_id = (await page.call("workspace_snapshot")).application
        .project.id;
      await page.call("project_translation_export", {
        project_id,
        path: again,
      });
      const first = JSON.parse(fs.readFileSync(again, "utf8")).lines[0];
      if (first.translation !== "Edited by hand.")
        throw new Error(`The import left "${first.translation}".`);
    },
  ],
];

/** Each message's rows and each choice in a game's map, in play order: what
 * players read, row by row. */
function shownRows(state, game) {
  const data = path.join(contentFolder(state.variants, game), "data");
  const map = JSON.parse(
    fs.readFileSync(path.join(data, "Map001.json"), "utf8"),
  );
  const shown = [];
  for (const event of map.events)
    for (const page of event?.pages ?? []) {
      let message = null;
      for (const command of [...page.list, { code: 0 }]) {
        if (command.code === 401) {
          message = [...(message ?? []), ...command.parameters[0].split("\n")];
          continue;
        }
        if (message?.length) shown.push(message);
        message = command.code === 101 ? [] : null;
        if (command.code === 102)
          shown.push(...command.parameters[0].map((choice) => [choice]));
      }
    }
  return shown;
}

/** Each message's and choice's text in a game's map, whitespace collapsed,
 * in play order: what players read, however its rows are laid out. */
const shownText = (state, game) =>
  shownRows(state, game)
    .map((rows) => rows.join(" ").replace(/\s+/g, " ").trim())
    .filter(Boolean);

/** Turns on First-line names in Context's speaker detection, as a user does
 * for a game whose messages name their speaker on a row of its own. */
async function firstLineNames(page) {
  await page.click("2Context");
  await page.click("Names & glossary");
  await page.click("Speaker detection");
  await page.click("First-line names");
  await page.click("Save & close");
  await until(
    "First-line names to be saved",
    async () =>
      (await page.call("workspace_snapshot")).guided.preferences.values
        .engine_options.FIRSTLINESPEAKERS === true,
  );
}

// The first-line-speaker game variant's message: its nameplate row and speech.
const nameplate = "新米警察官";
const nameplateSpeech =
  "「すいません‼ちょっと目を離したすきに\n　入り込みまして…‼";

const sharedFile = [
  [
    "Export the translated game's translation file from the Project page's Export/Import tab",
    async ({ page, state }) => {
      state.shared = path.join(state.work, "shared.json");
      await page.click("Project");
      await page.click("Export/Import");
      await chooseFile(
        { root: state.root, inspect: state.app.inspect },
        state.shared,
      );
      await page.click("Export…");
      await page.waitText("Saved ");
      const { lines } = JSON.parse(fs.readFileSync(state.shared, "utf8"));
      if (
        !lines.some(
          (line) => line.id.startsWith("Map001.json#") && line.translation,
        )
      )
        throw new Error("The export holds no translated map line.");
      if (!state.variants.includes("first-line-speaker")) return;
      // The nameplate is a line of its own, and its speech the next part.
      const name = lines.find((line) => line.source === nameplate);
      const speech = lines.find((line) => line.id === `${name?.id}~1`);
      const shape = (line) =>
        line && { kind: line.kind, speaker: line.speaker, source: line.source };
      const want = [
        { kind: "ui", speaker: null, source: nameplate },
        { kind: "dialogue", speaker: nameplate, source: nameplateSpeech },
      ];
      if (
        !/^Map001\.json#\/[^~]+$/.test(name?.id) ||
        JSON.stringify([shape(name), shape(speech)]) !== JSON.stringify(want)
      )
        throw new Error(
          `The export's nameplate lines: ${JSON.stringify([name, speech])}`,
        );
      // A file edited by hand may hold the speech on one row, too long for
      // a window's line, which Apply must wrap below the nameplate.
      const file = JSON.parse(fs.readFileSync(state.shared, "utf8"));
      const edited = file.lines.find((line) => line.id === speech.id);
      if (!edited?.translation)
        throw new Error(
          `The export's speech line has no translation: ${JSON.stringify(edited)}`,
        );
      edited.translation = edited.translation.replace(/\s*\n\s*/g, " ");
      fs.writeFileSync(state.shared, JSON.stringify(file));
    },
  ],
  [
    "Open an untranslated copy of the game with Guided steps and set it up",
    async ({ page, state }) => {
      state.guidedGame = state.game;
      state.game = path.join(path.dirname(state.game), "コピー");
      await makeGame(state.variants, state.game);
      await openFolder(page, state, state.game, "Guided steps");
      await setUp(page);
      if (state.variants.includes("first-line-speaker"))
        await firstLineNames(page);
    },
  ],
  [
    "Import the file on the Project page, then apply it in Translate: the copy shows the same text",
    async ({ page, state }) => {
      await page.click("Project");
      await page.click("Export/Import");
      await chooseFile(
        { root: state.root, inspect: state.app.inspect },
        state.shared,
      );
      await page.click("Import…");
      await page.waitText("Import translations?");
      await page.shot(path.join(state.work, "logs", "shared-import.png"));
      await page.click(/^Import [\d,]+ translations?$/);
      await page.waitText("Imported ");
      await page
        .click("Open Guided steps", 5_000)
        .catch(() => page.click("Translation"));
      await page.click("3Translate");
      for (const task of ["Database files", "Maps & events"]) {
        await page.click(task);
        await applyTask(page, task);
      }
      const theirs = shownText(state, state.guidedGame);
      const mine = shownText(state, state.game);
      if (JSON.stringify(mine) !== JSON.stringify(theirs))
        throw new Error(
          `The copy shows ${JSON.stringify(mine)}, the translated game ${JSON.stringify(theirs)}.`,
        );
      // A nameplate keeps its row, however the speech after it wraps.
      const first = (game) => shownRows(state, game).map((rows) => rows[0]);
      if (
        JSON.stringify(first(state.game)) !==
        JSON.stringify(first(state.guidedGame))
      )
        throw new Error(
          `The copy's messages start ${JSON.stringify(shownRows(state, state.game))}, the translated game's ${JSON.stringify(shownRows(state, state.guidedGame))}.`,
        );
    },
  ],
];

const assistantWrite = [
  "The assistant organizes and translates all the text, then writes it into the game",
  async ({ page, state }) => {
    await assistant(page, state, "organize");
    const run = JSON.parse(await assistant(page, state, "translate"));
    if (run.status !== "complete")
      throw new Error(`Run ${run.id}: ${run.status}, ${run.message || ""}`);
    await assistant(page, state, "write");
  },
];

// The unsent-lines game variant's messages of punctuation alone, and the
// English form DazedTL writes them in (results.unsent_line).
const unsentLines = { "「……」": '"……"', "！？": "!?" };

/** The punctuation-only lines the assistant extracted: no request of its run
 * sends them, the progress export marks their rows converted, and the game
 * holds them in English form. */
const unsentWritten = [
  "No request sends the lines of punctuation alone; the export marks them converted and the game holds them in English form",
  async ({ page, state }) => {
    const work = path.join(state.game, ".dazedtl/len-method/work");
    const read = (file) => JSON.parse(fs.readFileSync(file, "utf8"));
    const { run } = read(path.join(work, "scripted-assistant.json"));
    for (let index = 0, total = 1; index < total; index++) {
      const reply = await helper(
        page,
        state,
        "request",
        "--run",
        run,
        "--index",
        `${index}`,
      );
      total = reply.total;
      const sent = Object.values(reply.request.sources).filter(
        (source) => source in unsentLines,
      );
      if (sent.length)
        throw new Error(`Request ${index} sends ${sent.join(", ")}.`);
    }
    const rows = read(path.join(work, "translation-units.json")).parts.flatMap(
      (part) => read(path.join(state.game, part)).units,
    );
    const data = path.join(contentFolder(state.variants, state.game), "data");
    const lines = read(path.join(data, "Map001.json"))
      .events.flatMap((event) => event?.pages ?? [])
      .flatMap((page) => page.list)
      .filter((command) => command.code === 401)
      .map((command) => command.parameters[0]);
    for (const [source, english] of Object.entries(unsentLines)) {
      const row = rows.find((row) => row.source === source);
      if (!row?.converted || row.translation !== english)
        throw new Error(
          `The export's row of ${source}: ${JSON.stringify(row)}`,
        );
      if (!lines.includes(english) || lines.includes(source))
        throw new Error(`Map001.json doesn't hold ${source} as ${english}.`);
    }
    console.log(
      `\n  Written without a request: ${Object.values(unsentLines).join(", ")}`,
    );
  },
];

// The name-codes game variant's messages, as the request shows each to the
// model: actor 1 by the name the scripted glossary gives her.
const nameCodeLines = {
  "\\N[1]、こっちに来て。": "Mika、こっちに来て。",
  "\\V[7]は笑った。": "Mikaは笑った。",
};

/** The messages naming actor 1 by a code: the request Inspect shows holds
 * her name in their place, and the export and the game hold the codes the
 * scripted assistant answered with the name. */
const nameCodesWritten = [
  "A request shows actor 1's name for her codes; the export and the game hold the codes",
  async ({ page, state }) => {
    const work = path.join(state.game, ".dazedtl/len-method/work");
    const read = (file) => JSON.parse(fs.readFileSync(file, "utf8"));
    const { run } = read(path.join(work, "scripted-assistant.json"));
    const shown = new Set();
    for (let index = 0, total = 1; index < total; index++) {
      const reply = await helper(
        page,
        state,
        "request",
        "--run",
        run,
        "--index",
        `${index}`,
      );
      total = reply.total;
      for (const source of Object.values(reply.request.sources))
        if (source in nameCodeLines) {
          if (!reply.request.context.user.includes(nameCodeLines[source]))
            throw new Error(`Request ${index} doesn't show ${source} named.`);
          shown.add(source);
        }
    }
    if (shown.size !== Object.keys(nameCodeLines).length)
      throw new Error(`Only ${[...shown].join(", ")} reached a request.`);
    const rows = read(path.join(work, "translation-units.json")).parts.flatMap(
      (part) => read(path.join(state.game, part)).units,
    );
    const data = path.join(contentFolder(state.variants, state.game), "data");
    const lines = read(path.join(data, "Map001.json"))
      .events.flatMap((event) => event?.pages ?? [])
      .flatMap((page) => page.list)
      .filter((command) => command.code === 401)
      .map((command) => command.parameters[0]);
    for (const source of Object.keys(nameCodeLines)) {
      const code = source.slice(0, 5);
      const row = rows.find((row) => row.source === source);
      if (!row?.translation.endsWith(code) || row.translation.includes("Mika"))
        throw new Error(
          `The export's row of ${source}: ${JSON.stringify(row)}`,
        );
      if (!lines.includes(row.translation))
        throw new Error(`Map001.json doesn't hold ${row.translation}.`);
    }
    console.log(`\n  Shown named: ${Object.values(nameCodeLines).join(", ")}`);
  },
];

/** The QA bar of Progress's assistant phases: its state and detail line. */
const progressQa = (page) =>
  page.evaluate(`(() => {
    const step = [
      ...document.querySelectorAll("[aria-label='Assistant phases'] > li"),
    ].find((item) => item.querySelector("span")?.firstChild?.textContent === "QA");
    return step
      ? { state: step.dataset.state, detail: step.querySelector("small")?.textContent || "" }
      : null;
  })()`);

/** Waits until Progress's QA bar reads `state` with `detail`, then saves a
 * screenshot of it as logs/`shot`. */
async function progressShowsQa(page, state, want, shot) {
  if (!(await progressQa(page))) await page.click("Progress");
  await until(
    `Progress's QA phase to read ${JSON.stringify(want)}`,
    async () => {
      const shown = await progressQa(page);
      return (
        shown?.state === want.state && shown.detail === (want.detail || "")
      );
    },
  );
  await page.shot(path.join(state.work, "logs", shot));
}

// What the scripted reviewer adds to the line it corrects (qa_reviewer.py);
// fitting may break the line before it.
const qaCorrection = "(checked)";
// The village chief's last line, which the extractor of assistant-released
// misses, by its pointer in data/Map001.json.
const missedLine = "/events/1/pages/0/list/8/parameters/0";

/** The starting prompt's QA step for MV/MZ (TranslationService.prepare),
 * after the assistant wrote the game: play it, review and apply Text QA,
 * report the qa phase complete as qa's next step says, then play it again,
 * Progress holding QA at Final check until that playtest settles. */
const assistantQa = [
  [
    "The assistant plays the game, reviews and applies Text QA, and reports the qa phase complete",
    async ({ page, state }) => {
      const played = JSON.parse(await assistant(page, state, "play"));
      console.log(`\n  Playtest: ${played.next}`);
      // QA counts the line the extractor missed as never translated, and its
      // next step sends it back; the TitleMessage text no player sees stays
      // reported only.
      const prepared = await helper(page, state, "qa", "--prepare");
      if (!prepared.untranslated || !prepared.next.startsWith("untranslated "))
        throw new Error(
          `Text QA sent no never-translated text back: ${prepared.next}`,
        );
      const { translated, qa: after } = JSON.parse(
        await assistant(page, state, "untranslated"),
      );
      const locations = translated.map((row) => `${row.file}#${row.pointer}`);
      console.log(`  Translated what QA counted: ${locations.join(", ")}`);
      if (locations.join() !== `data/Map001.json#${missedLine}`)
        throw new Error(`Text QA counted ${locations.join(", ")}.`);
      if (after.untranslated)
        throw new Error(
          `Text QA still counts untranslated text: ${after.next}`,
        );
      const { corrected } = await reviewQa({ page, state });
      const data = path.join(contentFolder(state.variants, state.game), "data");
      if (
        !corrected.length ||
        !fs
          .readdirSync(data)
          .some((name) =>
            fs
              .readFileSync(path.join(data, name), "utf8")
              .includes(qaCorrection),
          )
      )
        throw new Error("Text QA's apply wrote no correction into the game.");
      await assistant(page, state, "qa-applied");
    },
  ],
  [
    "Progress holds QA at Final check until the playtest after QA's apply settles, then shows it done",
    async ({ page, state }) => {
      await progressShowsQa(
        page,
        state,
        { state: "current", detail: "Final check" },
        "qa-final-check.png",
      );
      const checked = JSON.parse(await assistant(page, state, "final-check"));
      console.log(`  Final check: ${checked.next}`);
      // The assistant's report of the playtest, which settled it.
      await page.waitText("Final check settled");
      await progressShowsQa(page, state, { state: "done" }, "qa-done.png");
    },
  ],
];

/** The project's API Batch run, as Progress reads it. */
async function batchRun(page) {
  const project = (await page.call("workspace_snapshot")).application.project;
  const { jobs } = await page.call("translation_state", {
    project_id: project.id,
  });
  return jobs.find((job) => job.kind === "translation" && job.mode === "batch");
}

// A Batch token allowance just above the database Batch the stand-in holds,
// about 116,000 tokens, so it leaves too little room for the Assistant-led
// run beside it.
const queuedAllowance = 150_000;

/** Shows the Assistant-led page's Progress tab, where its API runs are
 * approved. The page opens on Options until the assistant first uses the
 * project, and a background change never moves the user off it. */
async function openProgress(page) {
  await page.click("Translation");
  await page.click("Progress");
}

/** Opens `game` from the project menu, choosing `method` for a new game. */
async function openFolder(page, state, game, method) {
  await chooseFolder({ root: state.root, inspect: state.app.inspect }, game);
  const { project } = (await page.call("workspace_snapshot")).application;
  await page.click(project.name);
  await page.click("Open a game…");
  if (method) {
    await page.click(new RegExp(`^${method}`));
    await page.click(`Start with ${method}`);
  }
  await until(
    `${game} to open`,
    async () =>
      (await page.call("workspace_snapshot")).application.project?.source ===
      game,
  );
}

/** How many Batches the stand-in was asked to create. */
const created = (state) =>
  recordedRequests(path.join(state.work, "provider")).filter(
    (item) => item.method === "POST" && item.route === "/batches",
  ).length;

// Settings and Assistant-led preparation wait while a Guided run works, so
// both come before the database Batch, and the estimate is approved after it.
const queuedBatch = [
  [
    "Set the connection's Batch token allowance just above the database Batch",
    async ({ page }) => {
      const saved = await page.call("settings_get");
      const options = saved.modelOptions[model];
      if (!options)
        throw new Error("The stand-in model's options were not saved.");
      await page.call("settings_save", {
        revision: saved.revision,
        connection_id: saved.activeConnectionId,
        values: saved.values,
        model_options: {
          ...saved.modelOptions,
          [model]: { ...options, batchInputTokens: queuedAllowance },
        },
      });
    },
  ],
  [
    "Open a copy of the game Assistant-led, for an API Batch",
    async ({ page, state }) => {
      state.guidedGame = state.game;
      state.game = path.join(path.dirname(state.game), "コピー");
      await makeGame(state.variants, state.game);
      await openFolder(page, state, state.game, "Assistant-led");
      const { project } = (await page.call("workspace_snapshot")).application;
      const current = await page.call("translation_state", {
        project_id: project.id,
      });
      await page.call("translation_save", {
        project_id: project.id,
        revision: current.revision,
        values: { ...current.options, mode: "batch" },
      });
      await page.call("translation_prepare", { project_id: project.id });
    },
  ],
  [
    "The assistant sets up the game",
    ({ page, state }) => assistant(page, state, "setup"),
  ],
  [
    "The assistant organizes all the text into an API Batch estimate",
    ({ page, state }) => assistant(page, state, "organize", "--complete"),
  ],
  [
    "Back in the Guided game, submit the database as a Batch the stand-in holds",
    async (context) => {
      await openFolder(context.page, context.state, context.state.guidedGame);
      await context.page.click("Translation");
      await batch[1][1](context);
    },
  ],
  [
    "Approve the Assistant-led estimate on Progress; its first chunk waits unsent",
    async ({ page, state }) => {
      await openFolder(page, state, state.game);
      await openProgress(page);
      const before = created(state);
      await page.click("Approve and submit Batch");
      const run = await until("a chunk waiting for capacity", async () => {
        const job = await batchRun(page);
        return job?.batches?.[0]?.state === "queued" && job;
      });
      await page.waitText("Waiting for available Batch token capacity.");
      // Several polls later it still has sent nothing.
      await new Promise((resolve) => setTimeout(resolve, 12_000));
      const still = await batchRun(page);
      if (still.batches[0].state !== "queued" || created(state) !== before)
        throw new Error(
          `The chunk did not wait: ${JSON.stringify(still.batches[0])}`,
        );
      console.log(
        `\n  Run ${run.id}: ${run.batches.length} chunks, ${run.message}`,
      );
    },
  ],
  [
    "Release the held Batch; the queued chunk is sent and the run completes",
    async ({ page, state }) => {
      const modeFile = path.join(state.work, "provider/mode.json");
      const mode = JSON.parse(fs.readFileSync(modeFile, "utf8"));
      fs.writeFileSync(modeFile, JSON.stringify({ ...mode, hold: false }));
      const run = await until(
        "the Assistant-led run to complete",
        async () => {
          const job = await batchRun(page);
          if (["failed", "uncertain", "stopped"].includes(job.status))
            throw new Error(`Run ${job.id}: ${job.status}, ${job.message}`);
          return job.status === "complete" && job;
        },
        5 * 60_000,
      );
      if (run.batches.some((chunk) => chunk.state !== "complete" || !chunk.id))
        throw new Error(`Unsent chunks: ${JSON.stringify(run.batches)}`);
      console.log(`\n  Run ${run.id}: ${run.batches.length} chunks sent`);
    },
  ],
];

/** The project's newest Assistant-led run, as the helper reads it. */
async function organizedRun(page, state) {
  const remembered = JSON.parse(
    fs.readFileSync(
      path.join(state.game, ".dazedtl/len-method/work/scripted-assistant.json"),
      "utf8",
    ),
  );
  return helper(page, state, "run", "--run", remembered.run);
}

/** The units the scripted assistant organized whose source holds `text`. */
function unitsHolding(state, text) {
  const { units } = JSON.parse(
    fs.readFileSync(
      path.join(state.game, ".dazedtl/len-method/work/source-units.json"),
      "utf8",
    ),
  );
  return units.filter((unit) => unit.source.includes(text)).length;
}

/** Every job record saved in the scenario's profile that `match` picks. */
function savedJobs(state, match) {
  const found = [];
  const walk = (folder) => {
    for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
      const file = path.join(folder, entry.name);
      if (entry.isDirectory()) walk(file);
      else if (entry.name === "job.json") {
        const job = JSON.parse(fs.readFileSync(file, "utf8"));
        if (match(job)) found.push({ file, job });
      }
    }
  };
  walk(state.profile);
  return found;
}

// The waiting figures a restart keeps for repricing to read: the whole-game
// estimate and an Assistant-led quote waiting for approval. A Guided
// Translate estimate is a temporary preparation, which closing discards.
const waitingFigures = {
  whole: {
    match: (job) => job.action === "full_estimate" && job.status === "complete",
    figure: (job) => job.result,
  },
  assistant: {
    match: (job) =>
      job.kind === "translation" && job.status === "ready" && !!job.quote,
    figure: (job) => job.quote,
  },
};

/**
 * Saves every waiting figure as a release saved it before figures named
 * their price rules, then changed by `edit[kind](figure)`, while the app is
 * closed.
 */
function savedBeforePricingFix(state, restart, edit) {
  return restart(() => {
    for (const [kind, { match, figure }] of Object.entries(waitingFigures)) {
      const jobs = savedJobs(state, match);
      if (!jobs.length) throw new Error(`No waiting ${kind} figure was saved.`);
      for (const { file, job } of jobs) {
        delete figure(job).price_rules;
        edit[kind](figure(job));
        fs.writeFileSync(file, JSON.stringify(job, null, 2));
      }
    }
  });
}

/** The whole-game estimate, as Context shows it. */
async function wholeEstimate(page) {
  return (await page.call("workspace_snapshot")).guided.fullEstimate;
}

/** Estimates the whole game's cost again, as its Estimate again does. */
async function estimateWholeGame(page) {
  const project = (await page.call("workspace_snapshot")).application.project;
  await page.call("guided_full_estimate", { project_id: project.id });
  await page.idle();
  const estimate = await wholeEstimate(page);
  if (!estimate.current)
    throw new Error(
      `The whole-game estimate is not current: ${JSON.stringify(estimate)}`,
    );
  return estimate;
}

/** The Assistant-led quote's prices Progress shows. */
const quotePrices = ["cost", "live_cost", "batch_cost", "batch_cost_reused"];

const repriced = [
  [
    "Price the OpenAI preset's stand-in model so estimates cost something",
    async ({ page }) => {
      const saved = await page.call("settings_get");
      await page.call("settings_save", {
        revision: saved.revision,
        connection_id: saved.activeConnectionId,
        values: saved.values,
        model_options: {
          ...saved.modelOptions,
          [model]: {
            ...saved.modelOptions[model],
            inputRate: 30,
            outputRate: 120,
          },
        },
      });
    },
  ],
  [
    "Estimate the whole game's cost",
    async ({ page, state }) => {
      state.whole = await estimateWholeGame(page);
    },
  ],
  queuedBatch[1],
  queuedBatch[2],
  queuedBatch[3],
  [
    "Saved by a release before a pricing fix as Claude's estimate and an OpenAI quote from before cache counts, which can't be priced again: each asks to be estimated again, and Progress offers no Approve",
    async ({ page, state, restart }) => {
      page = await savedBeforePricingFix(state, restart, {
        whole: (result) => {
          for (const counts of Object.values(result.measured))
            counts.provider = "anthropic";
        },
        assistant: (quote) => {
          delete quote.cache_read_tokens;
          delete quote.cacheable_tokens;
        },
      });
      await openFolder(page, state, state.game);
      await openProgress(page);
      await page.waitText(
        "DazedTL corrected its prices after this estimate in a way that needs a new one.",
      );
      if (await page.locate("Approve and submit Batch"))
        throw new Error("An estimate priced by older rules can be approved.");
      await page.shot(path.join(state.work, "logs/assistant-outdated.png"));
      const outdated = await batchRun(page);
      await page.click("Estimate again");
      const fresh = await until(
        "a new Assistant-led estimate",
        async () => {
          const job = await batchRun(page);
          return job.id !== outdated.id && job.status === "ready" && job;
        },
        2 * 60_000,
      );
      if (fresh.pricing_changed || fresh.settings_changed)
        throw new Error(`The new estimate reads outdated: ${fresh.id}`);
      await openFolder(page, state, state.guidedGame);
      const whole = await wholeEstimate(page);
      if (whole.current !== false)
        throw new Error(
          `A Claude estimate priced by older rules reads current: ${JSON.stringify(whole)}`,
        );
      state.whole = await estimateWholeGame(page);
    },
  ],
  [
    "Saved by a release before a pricing fix at three times today's price: each shows today's price, and Approve freezes the price shown",
    async ({ page, state, restart }) => {
      await openFolder(page, state, state.game);
      const quote = (await batchRun(page)).quote;
      page = await savedBeforePricingFix(state, restart, {
        whole: (result) => {
          for (const task of result.tasks)
            for (const name of ["liveCost", "batchCost", "batchMaxCost"])
              task[name] *= 3;
        },
        assistant: (saved) => {
          for (const name of quotePrices)
            if (typeof saved[name] === "number") saved[name] *= 3;
        },
      });
      await openFolder(page, state, state.guidedGame);
      const whole = await wholeEstimate(page);
      const tasks = (value) => JSON.stringify(value.result.tasks);
      if (!whole.current || tasks(whole) !== tasks(state.whole))
        throw new Error(
          `The whole-game estimate shows ${tasks(whole)}, not today's ${tasks(state.whole)}.`,
        );
      await openFolder(page, state, state.game);
      await openProgress(page);
      const shown = await batchRun(page);
      for (const name of quotePrices)
        if (shown.quote[name] !== quote[name])
          throw new Error(
            `Progress shows ${name} ${shown.quote[name]}, not today's ${quote[name]}.`,
          );
      await page.shot(path.join(state.work, "logs/assistant-repriced.png"));
      await page.click("Approve and submit Batch");
      const approved = await until("the run's approval", async () => {
        const job = await batchRun(page);
        return job.approved && job;
      });
      const [frozen] = savedJobs(state, (job) => job.id === approved.id);
      if (JSON.stringify(frozen.job.quote) !== JSON.stringify(shown.quote))
        throw new Error(
          `Approve froze ${JSON.stringify(frozen.job.quote)}, not the shown ${JSON.stringify(shown.quote)}.`,
        );
    },
  ],
];

// The collapsed-line game's stand-in collapses every line holding it, so a
// Live run keeps each such line in Japanese.
const collapsed = "魔法の杖";

const reorganized = [
  [
    "Open the game Assistant-led for Live API, the stand-in connected",
    async ({ page, state }) => {
      await openGame(page, {
        root: state.root,
        inspect: state.app.inspect,
        game: state.game,
        method: "Assistant-led",
      });
      // The OpenAI preset asks for each line by key, as Assistant-led API
      // requests do, which the stand-in answers.
      await connect(page, "", "openai");
      const project_id = (await page.call("workspace_snapshot")).application
        .project.id;
      const current = await page.call("translation_state", { project_id });
      await page.call("translation_save", {
        project_id,
        revision: current.revision,
        values: { ...current.options, mode: "live" },
      });
      await page.call("translation_prepare", { project_id });
    },
  ],
  assistantLed[1],
  [
    "The assistant organizes all the text; approve its Live estimate on Progress and the run translates it",
    async ({ page, state }) => {
      await assistant(page, state, "organize", "--complete");
      const estimate = await organizedRun(page, state);
      await openProgress(page);
      await page.click("Approve and start Live");
      const run = await until(
        "the Live run to end",
        async () => {
          const job = await organizedRun(page, state);
          return (
            ["complete", "failed", "uncertain"].includes(job.status) && job
          );
        },
        5 * 60_000,
      );
      if (run.status !== "complete")
        throw new Error(`Run ${run.id}: ${run.status}, ${run.message}`);
      // Progress reads the lines the run kept in Japanese left.
      const project_id = (await page.call("workspace_snapshot")).application
        .project.id;
      const { text } = (await page.call("translation_state", { project_id }))
        .progress.metrics;
      const kept = unitsHolding(state, collapsed);
      if (text.translated !== text.total - kept)
        throw new Error(
          `Progress counts ${text.translated} of ${text.total} lines translated, with ${kept} kept in Japanese.`,
        );
      console.log(
        `\n  Run ${run.id}: ${estimate.quote.units} lines quoted, ${text.translated} of ${text.total} translated`,
      );
    },
  ],
  [
    "Inspect shows each later part of the long scene sent with the English the part before it got for the lines it quotes",
    async ({ page, state }) => {
      const { id } = await organizedRun(page, state);
      let previous = null;
      let parts = 0;
      for (let index = 0, total = 1; index < total; index++) {
        const reply = await helper(
          page,
          state,
          "request",
          "--run",
          id,
          "--index",
          `${index}`,
        );
        total = reply.total;
        const messages = reply.request.params.messages;
        const block = messages.findIndex((message) =>
          `${message.content}`.startsWith(
            "Preceding English Translation (already delivered):",
          ),
        );
        if (block >= 0) {
          // Guided's block, just before the request's own text, holds the
          // last lines the part before got.
          const lines = messages[block].content
            .split("\n```\n")[1]
            .replace(/\n```$/, "")
            .split("\n");
          const before = Object.keys(previous.request.sources)
            .slice(-lines.length)
            .map((unit) => previous.result.translations[unit]);
          if (
            block !== messages.length - 2 ||
            JSON.stringify(lines) !== JSON.stringify(before)
          )
            throw new Error(
              `Request ${index} was sent with ${JSON.stringify(lines)}, not the English the part before got: ${JSON.stringify(before)}.`,
            );
          parts += 1;
        }
        previous = reply;
      }
      if (!parts)
        throw new Error("No request was sent with the English before it.");
      console.log(
        `\n  ${parts} later part${parts === 1 ? "" : "s"} sent with the English before`,
      );
    },
  ],
  [
    "Add a glossary entry and organize again; the estimate quotes only the lines the run kept in Japanese",
    async ({ page, state }) => {
      // The game's own entries come before the base glossary's.
      const glossary = path.join(state.game, ".dazedtl/glossary.txt");
      const text = fs.readFileSync(glossary, "utf8");
      const base = text.indexOf("# ── Base Glossary");
      fs.writeFileSync(
        glossary,
        base < 0
          ? `${text}\nミカ (Mika)\n`
          : `${text.slice(0, base)}ミカ (Mika)\n\n${text.slice(base)}`,
      );
      await assistant(page, state, "organize", "--complete");
      const run = await organizedRun(page, state);
      const kept = unitsHolding(state, collapsed);
      console.log(
        `\n  Run ${run.id}: ${run.quote.units} lines quoted again; the first run kept ${kept}`,
      );
      if (!kept || run.quote.units !== kept)
        throw new Error(
          `The estimate after the glossary edit quotes ${run.quote.units} lines, not the ${kept} kept in Japanese.`,
        );
    },
  ],
];

const assistantUpdate = [
  "Apply the update and copy the post-update task, the starting prompt's steps from census in the project's mode and languages",
  async ({ page }) => {
    await page.click(`Apply update to ${release.version}`);
    await page.waitText("Translate the new text", 5 * 60_000);
    await page.idle();
    await page.click("Copy post-update task");
    await page.waitText("Task copied.");
    const project_id = (await page.call("workspace_snapshot")).application
      .project.id;
    const { prompt } = await page.call("translation_update_task", {
      project_id,
    });
    const start = (await page.call("translation_prepare", { project_id }))
      .handoff;
    // The language pair's note and the numbered steps come from the
    // starting prompt itself.
    const pair = start.slice(0, start.indexOf("Translate this game"));
    const steps = start.split("\n").filter((line) => /^\d+\. /.test(line));
    const missing = [
      `${pair}Official update "${release.version}" is applied`,
      "Selected execution mode: Assistant only",
      "with extraction active",
      "continue from step 4",
      "organize --complete",
      "Translate those yourself as step 6 says.",
      ...steps,
    ].filter((text) => !prompt.includes(text));
    if (missing.length)
      throw new Error(
        `The post-update task lacks: ${missing.map((text) => text.slice(0, 80)).join(" | ")}`,
      );
    console.log(`\n  ${prompt.split("\n").slice(0, 12).join("\n  ")}`);
  },
];

/** Brings in version 1.1 under Checkpoints, up to its preview. */
/**
 * Makes the developer's release (`makeRelease`) and brings it in from
 * Checkpoints as `version`, up to its preview, which must read as a patch
 * when it is one and as a complete game otherwise.
 */
async function bringIn(page, state, version, { patch = false } = {}) {
  const folder = path.join(
    state.work,
    `リリース ${version}`,
    gameName(state.variants),
  );
  await makeRelease(state.variants, folder, { patch });
  await page.click(/^Start (another )?game update$/);
  // Typed, as a user may instead of choosing it in the folder dialog.
  await page.type("#update-official-folder", folder);
  await page.waitText("Complete game");
  await page.type("#update-version", version);
  await page.click("Prepare new release");
  await page.click("Preview changes", 5 * 60_000);
  await page.waitText(`Apply update to ${version}`, 5 * 60_000);
  const text = await page.text();
  const heading = `Review update to ${version}`;
  const read = text
    .slice(text.indexOf(heading) + heading.length)
    .startsWith("Patch ·");
  if (read !== patch)
    throw new Error(
      `The ${version} release reads as ${read ? "a patch" : "a complete game"}.`,
    );
}

/** Brings in version 1.1 under Checkpoints, up to its preview. */
const updateGame = (options) => [
  [
    "Open Checkpoints, the translation's Apply already its checkpoint",
    async ({ page }) => {
      await page.click("Project");
      await page.click("Checkpoints");
      await page.waitText("Start game update");
    },
  ],
  [
    `Bring in version 1.1${options?.patch ? " as its new Game.rgss3a alone" : ""}, which changes a profile the translation changed and describes an armor`,
    ({ page, state }) => bringIn(page, state, release.version, options),
  ],
];

const stoppedUpdate = [
  ...updateGame(),
  [
    "Apply it, stopping at the conflict as an apply the app closed during does",
    async ({ page, state }) => {
      const project = (await page.call("workspace_snapshot")).application
        .project;
      const { jobs } = await page.call("translation_state", {
        project_id: project.id,
      });
      const preview = jobs.find(
        (job) => job.action === "version_preview" && job.status === "complete",
      );
      // The app's Apply resolves conflicts at once; stopping before that is
      // what an update interrupted mid-apply leaves for Checkpoints.
      runPython(
        pythonCommand(
          state,
          path.join(import.meta.dirname, "stopped_update.py"),
          state.root,
          path.join(state.profile, "workspace"),
          preview.id,
        ),
      );
      await page.waitText("Finish the interrupted update");
      await until("Checkpoints to offer to cancel the update", () =>
        page.locate("Cancel update & restore translation"),
      );
    },
  ],
];

const ace = (state) => state.variants[0] === "ace";

/** The game's database file `name` as JSON; a VX Ace game's converted copy. */
function gameJson(state, name) {
  const folder = ace(state)
    ? path.join(state.game, "ace_json")
    : path.join(contentFolder(state.variants, state.game), "data");
  return JSON.parse(fs.readFileSync(path.join(folder, name), "utf8"));
}

/** The bytes of the game's data files, which Apply writes, by path. */
function gameData(state) {
  const folders = ace(state)
    ? ["Data", "ace_json"]
    : [
        path.relative(state.game, contentFolder(state.variants, state.game)),
      ].map((folder) => path.posix.join(folder, "data"));
  const files = new Map();
  for (const folder of folders)
    for (const entry of fs.readdirSync(path.join(state.game, folder), {
      withFileTypes: true,
    }))
      if (entry.isFile())
        files.set(
          `${folder}/${entry.name}`,
          fs.readFileSync(path.join(state.game, folder, entry.name)),
        );
  return files;
}

/**
 * The text a player's game reads from the patch's database file `name`:
 * an Ace game's packed Data, whose strings Ruby keeps as UTF-8, or an MV or
 * MZ file without the `_original` copies DazedTL keeps in it.
 */
function patchText(state, files, name) {
  const entry = ace(state)
    ? `Data/${path.basename(name, ".json")}.rvdata2`
    : path.posix.join(
        path.relative(state.game, contentFolder(state.variants, state.game)),
        "data",
        name,
      );
  const data = files.get(entry);
  if (!data) throw new Error(`The patch ZIP lacks ${entry}.`);
  return ace(state)
    ? data.toString("utf8")
    : JSON.stringify(JSON.parse(data.toString("utf8")), (key, value) =>
        key === "_original" ? undefined : value,
      );
}

/** Requires the patch's database to hold the game's translated `texts`
 * and none of the Japanese `left` texts. */
function requirePatchText(state, files, name, texts, left = []) {
  const text = patchText(state, files, name);
  const missing = texts.filter((value) => !text.includes(value));
  if (texts.some((value) => !translated(value)) || missing.length)
    throw new Error(
      `The patch ZIP's ${name} lacks the translation ${JSON.stringify(missing.length ? missing : texts)}.`,
    );
  const kept = left.filter((value) => text.includes(value));
  if (kept.length)
    throw new Error(`The patch ZIP's ${name} holds ${JSON.stringify(kept)}.`);
}

/** The Status column of file `name` in the open translation task. */
async function fileStatus(page, name) {
  const lines = (await page.text()).split("\n");
  const at = lines.indexOf(name, lines.indexOf("Status"));
  return at < 0 ? null : lines[at + 2];
}

/** The armor version 1.1 describes. */
const armor = (state) => gameJson(state, "Armors.json")[1];

/** Releases, updates, releases again and undoes, the Apply before the undo
 * kept to compare with. With `patch`, version 1.1 is an encrypted game's
 * new archive alone, and a complete 1.2 is previewed after it. */
function releasing({ patch = false } = {}) {
  let before;
  const complete = [
    "Bring in a complete version 1.2, which reads as a complete game and removes nothing, then discard it",
    async ({ page, state }) => {
      await page.click("Project");
      await page.click("Checkpoints");
      await bringIn(page, state, "1.2");
      const text = await page.text();
      if (/\d\sremoved\b|applying it removes them/.test(text))
        throw new Error("The complete release would remove the game's files.");
      await page.click("Discard release");
      await until("Checkpoints to offer a new update", () =>
        page.locate(/^Start (another )?game update$/),
      );
    },
  ];
  return [
    [
      "Build a patch ZIP of the translation",
      async ({ page, state }) => {
        const files = await buildPatch(page);
        // The first actor's words, all translated.
        const [, actor] = gameJson(state, "Actors.json");
        requirePatchText(state, files, "Actors.json", [
          actor.name,
          actor.nickname,
          actor.profile,
        ]);
      },
    ],
    ...updateGame({ patch }),
    [
      "Check the preview's counts stay within the release's changes",
      async ({ page }) => {
        const text = await page.text();
        // The heading's version runs into the counts after it.
        const heading = `Review update to ${release.version}`;
        const after = text.slice(text.indexOf(heading) + heading.length);
        // The checkpoints of each version follow the review.
        const end = after.search(/\nVersion \d/);
        const review = end < 0 ? after : after.slice(0, end);
        // Counts keep their words together with no-break spaces.
        const count = (words) =>
          Number(
            new RegExp(`(\\d[\\d,]*)\\s${words.replaceAll(" ", "\\s")}`).exec(
              review,
            )?.[1] ?? 0,
          );
        const files = count("added") + count("changed") + count("removed");
        const lines = count("lines? to translate");
        const stay = count("translations? stays?");
        // The release changes a profile and describes an armor, and every
        // other translation stays. Set up's own files, such as Forge, are
        // none of its changes. VX Ace's archive patch also changes their
        // Data files.
        if (
          count("removed") ||
          review.includes("applying it removes them") ||
          /Forge|plugins\.js/.test(review) ||
          files > (patch ? 4 : 2) ||
          lines < 1 ||
          lines > 3 ||
          stay < 1
        )
          throw new Error(
            `The preview reads out of bounds: ${review.split("\n").slice(0, 4).join(" | ")}`,
          );
      },
    ],
    [
      "Apply the update, keeping the translation, the changed file Outdated",
      async ({ page, state }) => {
        await page.click(`Apply update to ${release.version}`);
        await page.waitText("Translate the new text", 5 * 60_000);
        await page.idle();
        const actors = gameJson(state, "Actors.json");
        if (!translated(actors[1].name) || !translated(actors[1].nickname))
          throw new Error(
            `The update lost the translation: ${actors[1].name}, ${actors[1].nickname}.`,
          );
        if (actors[1].profile !== release.profile)
          throw new Error(
            `The update kept no new profile: ${JSON.stringify(actors[1].profile)}.`,
          );
        if (armor(state).description !== release.description)
          throw new Error("The update brought in no armor description.");
        // An Ace game reads only an archive beside it, untranslated.
        const archive = fs
          .readdirSync(state.game)
          .find((name) => /^game\.rgss/i.test(name));
        if (archive)
          throw new Error(`The update put ${archive} beside the game's Data.`);
        // The task opens with the files the update changed selected.
        await page.click("Open Database files");
        await page.waitText("Reload from game…");
        for (const name of ["Actors.json", "Armors.json"]) {
          const status = await fileStatus(page, name);
          if (!status || ["Applied", "Done", "Ready to apply"].includes(status))
            throw new Error(`After the update ${name} reads ${status}.`);
        }
      },
    ],
    [
      "Reload, translate and apply what the update brought, then build the patch again",
      async ({ page, state }) => {
        await page.click("Reload from game…");
        await page.click("Reload files");
        await page.waitText("reloaded from the game");
        await page.idle();
        await translateTask(page, "Database files");
        before = gameData(state);
        await applyTask(
          page,
          "Database files",
          () =>
            translated(gameJson(state, "Actors.json")[1].profile) &&
            translated(armor(state).description),
        );
        const files = await buildPatch(page);
        requirePatchText(
          state,
          files,
          "Actors.json",
          [gameJson(state, "Actors.json")[1].profile],
          [release.profile],
        );
        requirePatchText(
          state,
          files,
          "Armors.json",
          [armor(state).description],
          [release.description],
        );
      },
    ],
    [
      "Undo that Apply in Checkpoints",
      async ({ page, state }) => {
        await page.click("Project");
        await page.click("Checkpoints");
        // The update's summary and task row read the current lines, none left.
        const finished = await page.text();
        const summary = /\nTranslate the new text\n+(.*)\n/.exec(finished)?.[1];
        const row = /\nDatabase files\n(.*)\n/.exec(finished)?.[1];
        if (
          // The release sends one translation back and keeps the others.
          !summary?.includes("back\u00a0to\u00a0Japanese") ||
          // Counts keep their words together with no-break spaces.
          /lines?\sto\stranslate/.test(summary) ||
          row !== "Actors.json, Armors.json"
        )
          throw new Error(
            `Translate the new text reads "${summary}" and "${row}".`,
          );
        // The newest checkpoint comes first.
        await page.click(/^More actions for Apply Database files,/);
        await page.click(/^Undo this change/);
        await page.waitText("Undone;");
        await page.idle();
        const now = gameData(state);
        const differ = [...new Set([...now.keys(), ...before.keys()])].filter(
          (name) => !now.get(name)?.equals(before.get(name) ?? Buffer.alloc(0)),
        );
        if (differ.length)
          throw new Error(
            `After the undo the game's ${differ.join(", ")} differ from before the Apply.`,
          );
        await page.click("Translation");
        await page.click(/^3Translate/);
        await page.click("Database files");
        await page.waitText("Reload from game…");
        const status = await fileStatus(page, "Actors.json");
        if (status !== "Ready to apply")
          throw new Error(`After the undo Actors.json reads ${status}.`);
        await page.click(/^5Release/);
        await page.waitText("Last saved patch ZIP\nOutdated");
      },
    ],
    ...(patch ? [complete] : []),
  ];
}

/**
 * Clicks the control named `name`, which copies a task, and returns the text
 * it copied: the app's main process, at the inspector port, hands it over
 * instead of the clipboard.
 */
async function copyTask(page, state, name) {
  const main = await Page.connect(state.app.inspect, {
    root: state.root,
    node: true,
  });
  try {
    await main.evaluate(`(() => {
      const { clipboard } = process.mainModule.require("electron");
      globalThis.scenarioCopies = [];
      clipboard.writeText = (text) => void globalThis.scenarioCopies.push(text);
    })()`);
    await page.click(name);
    return await until(`"${name}" to copy its task`, () =>
      main.evaluate("globalThis.scenarioCopies[0]"),
    );
  } finally {
    main.close();
  }
}

/** Ticks an image's tile in Images to translate, as a click on its box. */
async function tickImage(page, filename) {
  const at = await page.evaluate(`(() => {
    const box = document.querySelector(${JSON.stringify(`input[aria-label="Select ${filename}"]`)});
    box.scrollIntoView({ block: "center" });
    const { x, y, width, height } = box.getBoundingClientRect();
    return { x: x + width / 2, y: y + height / 2 };
  })()`);
  for (const type of ["mousePressed", "mouseReleased"])
    await page.send("Input.dispatchMouseEvent", {
      type,
      ...at,
      button: "left",
      clickCount: 1,
    });
}

/** The lettered images of the lettered-images game and the notes the user
 * writes on them. */
const lettered = ["text_0000.png", "text_0001.png"];
const revisionNotes = {
  "img/pictures/text_0000.png": "Make the title twice as big.",
  "img/pictures/text_0001.png": "Translate the sign's lettering too.",
};
/** The loose-images game's lettered picture, outside img/ and Graphics/. */
const loosePicture = `images/${lettered[0]}`;
const notesField = 'dialog textarea[aria-label="Image revision notes"]';

/** Opens `filename` in Compare images from every image's view. */
async function compareImage(page, filename) {
  await page.click(/^All images/);
  await page.click(`Compare ${filename}`);
  await until(`Compare images to show ${filename}`, () =>
    page.evaluate(
      `!!document.querySelector(${JSON.stringify(notesField)})?.getClientRects().length && document.querySelector("dialog").innerText.includes(${JSON.stringify(filename)})`,
    ),
  );
}

const compareText = (page) =>
  page.evaluate(`document.querySelector("dialog").innerText`);

async function closeCompare(page) {
  await page.click("Close");
  await until(
    "Compare images to close",
    async () =>
      !(await page.evaluate(
        `!!document.querySelector(${JSON.stringify(notesField)})?.getClientRects().length`,
      )),
  );
}

/** The revision note Compare images shows for `filename`. */
async function shownNote(page, filename) {
  await compareImage(page, filename);
  const note = await page.evaluate(
    `document.querySelector(${JSON.stringify(notesField)}).value`,
  );
  await closeCompare(page);
  return note;
}

/** Fails unless Compare images shows each image's revision note. */
async function notesShown(page, when) {
  for (const [id, note] of Object.entries(revisionNotes)) {
    const shown = await shownNote(page, path.basename(id));
    if (shown !== note)
      throw new Error(
        `${when}, Compare images shows ${JSON.stringify(shown)} as ${id}'s note.`,
      );
  }
}

const imagesProject = async (page) =>
  (await page.call("workspace_snapshot")).application.project.id;

/** The image `id` as the Images list reads it. */
async function imageRow(page, id) {
  const { items } = await page.call("images_list", {
    project_id: await imagesProject(page),
    asset_id: id,
    limit: 1,
  });
  return items[0];
}

/** Answers the copied investigation task `text` as an assistant does,
 * excluding the image `excluded`, finding the other lettered ones uncertain
 * and the rest without text, so the investigation ticks none. */
function investigateImages(text, excluded) {
  const file = /using request (.+?\.json)\./.exec(text)?.[1];
  if (!file) throw new Error("The copied task names no request.");
  const request = JSON.parse(fs.readFileSync(file, "utf8"));
  const assets = request.assets.map((asset) => ({
    id: asset.id,
    sourceHash: asset.sourceHash,
    classification:
      asset.id === excluded
        ? "excluded"
        : path.basename(asset.id).startsWith("text_")
          ? "uncertain"
          : "no_text",
    method: "visual",
    examined: true,
    reason: asset.id === excluded ? "The scripted assistant set it aside." : "",
    evidence: "contact sheet",
    variants: [],
  }));
  fs.writeFileSync(
    request.report,
    JSON.stringify({
      version: 1,
      kind: "discovery",
      projectId: request.projectId,
      requestId: request.id,
      inventoryRevision: request.inventoryRevision,
      complete: true,
      assets,
    }),
  );
}

/** Answers the copied image task `text` as the scripted assistant, giving
 * an error for the images whose IDs are in `errors`. */
function editImages(state, text, errors = []) {
  const request = /using request (.+?\.json)\./.exec(text)?.[1];
  if (!request) throw new Error("The copied task names no request.");
  runPython(
    pythonCommand(
      state,
      path.join(import.meta.dirname, "assistant.py"),
      "edit-images",
      "--game",
      state.game,
      "--request",
      request,
      ...errors.flatMap((id) => ["--error", id]),
    ),
  );
  return JSON.parse(fs.readFileSync(request, "utf8"));
}

/** The working copy of image `id` that `request` names, as it holds now. */
const editedCopy = (state, request, id) =>
  fs.readFileSync(
    path.join(
      state.game,
      request.assets.find((asset) => asset.id === id).editable,
    ),
  );

/** Applies the images ready to apply through Guided's review of them. */
async function applyImages(page, count) {
  const images = count === 1 ? "1 image" : `${count} images`;
  await page.click(`Apply to game (${count})`);
  await page.click(`Apply ${images}`);
  await page.idle();
}

/** The steps of the images-revised scenario. */
const imagesRevised = () => {
  // The revision task the footer copied, which the assistant answers.
  let revisionTask = "";
  // The editing request of that task, naming each image's working copy.
  let revision;
  return [
    [
      "Translate a lettered image the investigation excluded and apply it",
      async ({ page, state }) => {
        await page.click("3Translate");
        await page.click(/^Images\b/);
        await page.waitText(lettered[1]);
        // An exclusion is a finding that leaves the image unticked, not a
        // skip, so the user can still tick the image and translate it.
        const [id] = Object.keys(revisionNotes);
        investigateImages(
          await copyTask(page, state, "Copy investigation task"),
          id,
        );
        await until("the investigation's findings", async () => {
          const row = await imageRow(page, id);
          return row?.classification === "excluded" && row.state !== "skipped";
        });
        const { selection } = await page.call("images_state", {
          project_id: await imagesProject(page),
        });
        if (selection.length)
          throw new Error(`The investigation ticked ${selection.join(", ")}.`);
        await tickImage(page, lettered[0]);
        const request = editImages(
          state,
          await copyTask(page, state, "Copy translation task (1)"),
        );
        await applyImages(page, 1);
        await until(
          "the image to read Applied",
          async () => (await imageRow(page, id))?.state === "applied",
        );
        if (
          !fs
            .readFileSync(path.join(state.game, id))
            .equals(editedCopy(state, request, id))
        )
          throw new Error("The game's image is not the edited copy.");
      },
    ],
    [
      "Write revision notes on it and on an image never translated in Compare images",
      async ({ page, state }) => {
        for (const [id, note] of Object.entries(revisionNotes)) {
          await compareImage(page, path.basename(id));
          await page.type(notesField, note);
          if (id.endsWith(lettered[0])) {
            await until("the note's hint", async () =>
              (await compareText(page)).includes(
                "Kept with this image until your assistant's report answers it.",
              ),
            );
            await page.shot(path.join(state.work, "logs/compare-note.png"));
          }
          await closeCompare(page);
        }
        // The notes save with the list.
        await until("the notes to save", async () => {
          const { notes } = await page.call("images_state", {
            project_id: await imagesProject(page),
          });
          return Object.entries(revisionNotes).every(
            ([id, note]) => notes?.[id]?.text === note,
          );
        });
      },
    ],
    [
      "The notes stay after leaving Images and restarting the app",
      async ({ page, state, restart }) => {
        await notesShown(page, "After closing Compare images");
        await page.click("Database files");
        await page.waitText("Names, descriptions and interface text.");
        await page.click(/^Images\b/);
        await notesShown(page, "After leaving Images");
        page = await restart(async () => {});
        await page.click("Translation");
        await page.click(/^Images\b/);
        await notesShown(page, "After a restart");
        await until("the footer's revision task", () =>
          page.locate("Copy revision task (2)"),
        );
        await page.shot(path.join(state.work, "logs/footer-revision-task.png"));
        // The task card says which images hold the notes and lists them all,
        // even from a search that hides them.
        await page.type('input[aria-label="Search images"]', "cg");
        await page.click("2 images have revision notes");
        await until(
          "the Notes view to list the noted images",
          async () =>
            (await page.evaluate(
              `[...document.querySelectorAll(".image-grid:not([inert]) .image-tile-name")].map((name) => name.textContent).join()`,
            )) === lettered.join(),
        );
        await page.shot(path.join(state.work, "logs/notes-view.png"));
      },
    ],
    [
      "Copy revision task (2) in the footer sends both notes in one task",
      async ({ page, state }) => {
        const text = await copyTask(page, state, "Copy revision task (2)");
        const request = /using request (.+?\.json)\./.exec(text)?.[1];
        const { assets } = JSON.parse(fs.readFileSync(request, "utf8"));
        const sent = Object.fromEntries(
          assets.map((asset) => [asset.id, asset.revisionNotes]),
        );
        if (JSON.stringify(sent) !== JSON.stringify(revisionNotes))
          throw new Error(`The revision task sent ${JSON.stringify(sent)}.`);
        for (const [id, note] of Object.entries(revisionNotes))
          if (!text.includes(`- ${id}: ${note}`))
            throw new Error(`The copied task does not list ${id}'s note.`);
        revisionTask = text;
        await compareImage(page, lettered[0]);
        await until("the sent note's hint", async () =>
          (await compareText(page)).includes("Sent to your assistant"),
        );
        await page.shot(path.join(state.work, "logs/compare-sent.png"));
        await closeCompare(page);
      },
    ],
    [
      "The assistant revises the applied image and fails the other; the answered note joins its revision history",
      async ({ page, state }) => {
        const [revised, failed] = Object.keys(revisionNotes);
        revision = editImages(state, revisionTask, [failed]);
        await until("the revised image to read Ready to apply", async () => {
          return (await imageRow(page, revised))?.state === "ready";
        });
        await compareImage(page, lettered[0]);
        const history = await until(
          "Compare images to show the answered note in Revision history",
          async () => {
            const note = await page.evaluate(
              `document.querySelector(${JSON.stringify(notesField)}).value`,
            );
            const text = await compareText(page);
            const shown = text.split("Revision history\n")[1] || "";
            return !note && shown.includes(revisionNotes[revised]) && shown;
          },
        );
        // Newest first: the revision, then the first apply.
        if (!/^Revised .*\n.*\n[^]*Applied to the game /.test(history))
          throw new Error(`Revision history reads ${JSON.stringify(history)}.`);
        await page.shot(path.join(state.work, "logs/compare-history.png"));
        await closeCompare(page);
        // The failed image's note waits for another task.
        const note = await shownNote(page, lettered[1]);
        if (note !== revisionNotes[failed])
          throw new Error(
            `The failed image's note reads ${JSON.stringify(note)}.`,
          );
      },
    ],
    [
      "Apply to game puts the revised image back in the game",
      async ({ page, state }) => {
        const id = Object.keys(revisionNotes)[0];
        const before = fs.readFileSync(path.join(state.game, id));
        await applyImages(page, 1);
        const row = await until(
          "the revised image to read Applied",
          async () => {
            const found = await imageRow(page, id);
            return found?.state === "applied" && found;
          },
        );
        const game = fs.readFileSync(path.join(state.game, id));
        if (
          game.equals(before) ||
          !game.equals(editedCopy(state, revision, id))
        )
          throw new Error("The game's image is not the revised copy.");
        const kinds = row.revisions.map((entry) => entry.kind).join(", ");
        if (kinds !== "apply, revision, apply")
          throw new Error(`The image's revisions read ${kinds}.`);
        await compareImage(page, lettered[0]);
        const text = await compareText(page);
        if (!/^Applied\n/m.test(text.split("Zoom")[0]))
          throw new Error("Compare images does not read Applied.");
        await closeCompare(page);
      },
    ],
  ];
};

/**
 * @type {Record<string, { description: string, game?: string,
 *   from?: "previous", upgrade?: boolean,
 *   steps: () => [string, (context: any) => Promise<unknown>][] }>}
 */
export const scenarios = {
  fresh: {
    description: "An untouched game and an empty profile.",
    steps: () => [],
  },
  opened: {
    description: "The game open in Guided steps, before setup.",
    steps: () => [open],
  },
  "set-up": {
    description: "Set up in Guided steps, the stand-in provider connected.",
    steps: () => [open, ...setup],
  },
  translated: {
    description:
      "Database, maps and events translated live by the stand-in and applied.",
    steps: () => [open, ...setup, ...translateAll],
  },
  "lmstudio-plamo": {
    description:
      "translated through the LM Studio preset with PLaMo 3 Translate, which the stand-in answers as LM Studio does with that model's chat template, refusing any request the template can't render: one line a call, with its glossary and earlier lines, and no instructions or JSON.",
    steps: () => [
      open,
      setup[0],
      [
        "Connect LM Studio with PLaMo 3 Translate",
        ({ page }) => connect(page, "", "lmstudio", "plamo-3-translate-8b"),
      ],
      ...translateAll,
      plamoRequests,
    ],
  },
  "update-stopped": {
    description:
      "Translated and applied, then version 1.1 brought in under Checkpoints, its apply stopped at Git's conflict in Actors.json; Checkpoints offers to continue or cancel.",
    steps: () => [open, ...setup, ...translateAll, ...stoppedUpdate],
  },
  released: {
    description:
      "Translated, applied and released as a patch ZIP, then updated to version 1.1 to the end, its new text translated and released again, and that Apply undone in Checkpoints.",
    steps: () => [open, ...setup, ...translateAll, ...releasing()],
  },
  "released-ace": {
    description:
      "released on a VX Ace game shipped as an encrypted Game.rgss3a, its 1.1 a patch of the new Game.rgss3a alone; a complete 1.2 is then previewed and discarded.",
    game: "ace+encrypted",
    steps: () => [
      open,
      ...setup,
      ...translateAll,
      ...releasing({ patch: true }),
    ],
  },
  "released-mv": {
    description: "released on an RPG Maker MV game deployed in www.",
    game: "mv",
    steps: () => [open, ...setup, ...translateAll, ...releasing()],
  },
  "qa-done": {
    description:
      "Translated and applied, then Text QA reviewed by a scripted assistant, one correction applied.",
    steps: () => [open, ...setup, ...translateAll, qa],
  },
  "plugins-applied": {
    description:
      "Text QA's correction applied, then the plugin-text game's Plugin files translated by a scripted assistant and applied.",
    game: "plugin-text",
    steps: () => [open, ...setup, ...translateAll, qa, plugins],
  },
  moved: {
    description:
      "plugins-applied with a whole-game estimate and a Text QA task reviewing every line, then the game moved into a Game folder inside its own and opened there, then renamed while Compare models shows and found from the Project page; each must keep the project, its estimates and its Text QA task unchanged.",
    game: "plugin-text",
    steps: () => [open, ...setup, ...translateAll, qa, plugins, ...moved],
  },
  "moved-relabeled": {
    description:
      "moved, its project's engine saved as Investigation pending each time, as versions before 2.33.2 saved it once the old folder was opened again, and the Game folder first opened as an empty project.",
    game: "plugin-text",
    steps: () => [open, ...setup, ...translateAll, qa, plugins, ...relabeled],
  },
  "assistant-led": {
    description:
      "An Assistant-led project, the assistant translating itself: set up, text organized, the first request translated and the rest waiting.",
    steps: () => assistantLed,
  },
  images: {
    description:
      "An Assistant-led project on the many-images game, its images indexed and investigated by the assistant, which recommended the 40 with lettering.",
    game: "many-images",
    steps: () => [
      assistantLed[0],
      [
        "The assistant indexes and investigates the images",
        async ({ page, state }) => {
          console.log(`\n  ${(await assistant(page, state, "images")).trim()}`);
        },
      ],
    ],
  },
  "images-revised": {
    description:
      "A Guided project on the lettered-images game: one lettered image the investigation excluded, ticked, translated by a scripted assistant and applied, revision notes written on it and on the other in Compare images, kept through leaving Images and a restart and sent in one revision task from the footer; the assistant revises the applied image and fails the other, whose note waits, and Apply to game puts the revised image back.",
    game: "lettered-images",
    steps: () => [open, setup[0], ...imagesRevised()],
  },
  "images-released": {
    description:
      "A Guided project on a VX Ace game whose lettered title picture sits in an images folder outside Graphics, which Images suggests: the game's text translated, the picture translated by a scripted assistant and applied, and a patch ZIP built in Release that holds the applied picture.",
    game: "ace+loose-images",
    steps: () => [
      open,
      ...setup,
      ...translateAll,
      [
        "Translate the lettered picture in the suggested images folder and apply it",
        async ({ page, state }) => {
          await page.click(/^Images\b/);
          await page.waitText(lettered[0]);
          await tickImage(page, lettered[0]);
          const request = editImages(
            state,
            await copyTask(page, state, "Copy translation task (1)"),
          );
          await applyImages(page, 1);
          await until(
            "the picture to read Applied",
            async () =>
              (await imageRow(page, loosePicture))?.state === "applied",
          );
          state.loosePicture = editedCopy(state, request, loosePicture);
        },
      ],
      [
        "Build a patch ZIP that holds the applied picture",
        async ({ page, state }) => {
          const files = await buildPatch(page);
          if (!files.get(loosePicture)?.equals(state.loosePicture))
            throw new Error(
              `The patch ZIP lacks the applied ${loosePicture}: ${[...files.keys()].join(", ")}.`,
            );
        },
      ],
    ],
  },
  "images-archived": {
    description:
      "An Assistant-led project on the wolf game: the assistant decodes Data/Picture.wolf into a folder, translates its lettered title through the Images steps on that folder, packs the archive again and checkpoints it into the patch, whose download holds the title only inside the archive; Release builds a clean game ZIP without the decoded folder, and the apply is undone in Checkpoints and put back.",
    game: "wolf",
    steps: () => [
      assistantLed[0],
      assistantLed[1],
      [
        "The assistant translates the archived images and packs them again",
        async ({ page, state }) => {
          const project_id = (await page.call("workspace_snapshot")).application
            .project.id;
          const { handoff } = await page.call("translation_prepare", {
            project_id,
          });
          if (!handoff.includes("images --scan --root <folder>"))
            throw new Error(
              "The starting prompt names no decoded image folder.",
            );
          console.log(
            `\n  ${(await assistant(page, state, "archived-images")).trim().replaceAll("\n", "\n  ")}`,
          );
        },
      ],
      [
        "Release builds a clean game ZIP with the archive the image was packed into, not the decoded image",
        async ({ page }) => {
          await page.click("Release");
          const [folder, name] = await page.evaluate(
            `[document.querySelector("[aria-label='Save in']").value, document.querySelector(".guided-package-fields input").value]`,
          );
          await page.click("Build clean game ZIP");
          // Done, not Outdated, with the applied image it leaves out.
          await page.waitText("Last saved game ZIP\nDone", 5 * 60_000);
          const top = name.replace(/\.zip$/, "");
          const files = [...entries(fs.readFileSync(path.join(folder, name)))]
            .map((entry) => entry.path)
            .filter((entry) => !entry.endsWith("/"));
          if (
            !files.includes(`${top}/Data/Picture.wolf`) ||
            files.some((entry) => entry.startsWith(`${top}/decoded/`))
          )
            throw new Error(`The clean game ZIP holds ${files.join(", ")}.`);
        },
      ],
      [
        "Undo the image apply in Checkpoints, then undo the undo",
        async ({ page, state }) => {
          const project_id = (await page.call("workspace_snapshot")).application
            .project.id;
          const title = path.join(state.game, "decoded/Picture/text_title.png");
          const translated = fs.readFileSync(title);
          // The decoded original Images kept when it prepared the title.
          const original = fs.readFileSync(
            path.join(
              state.game,
              ".dazedtl/image_manager/guided/originals/decoded/Picture/text_title.png",
            ),
          );
          const applied = async () =>
            (await page.call("images_state", { project_id })).counts.applied;
          await page.click("Project");
          await page.click("Checkpoints");
          await page.click(/^More actions for Apply translated images,/);
          await page.click(/^Undo this change/);
          await page.waitText("Undone;");
          await page.idle();
          // It deleted the decoded title, which the archive packed again
          // would then lose.
          if (
            !fs.existsSync(title) ||
            !fs.readFileSync(title).equals(original) ||
            (await applied()) !== 0
          )
            throw new Error("The undo left the decoded title unrestored.");
          await page.click(
            /^More actions for Undid “Apply translated images”,/,
          );
          await page.click(/^Undo this change/);
          await until("the redo to finish", async () =>
            (await page.text()).includes("Redid “Apply translated images”"),
          );
          await page.idle();
          if (
            !fs.readFileSync(title).equals(translated) ||
            (await applied()) !== 1
          )
            throw new Error("Undoing the undo left the title untranslated.");
        },
      ],
    ],
  },
  "images-kirikiri": {
    description:
      "An Assistant-led project on the KiriKiri game: the assistant unpacks data.xp3 with Len's XP3 tool into a folder, translates its lettered BMP title screen and TLG menu through the Images steps on that folder, each applied in its own format, then packs them into a patch.xp3 and checkpoints it; Images lists both under their own names, applied.",
    game: "kirikiri",
    steps: () => [
      assistantLed[0],
      assistantLed[1],
      [
        "The assistant translates the images in data.xp3 and packs them into patch.xp3",
        async ({ page, state }) => {
          console.log(
            `\n  ${(await assistant(page, state, "kirikiri-images")).trim().replaceAll("\n", "\n  ")}`,
          );
        },
      ],
      [
        "Images lists the BMP and the TLG under their own names, applied",
        async ({ page }) => {
          for (const id of [
            "decoded/data/image/text_title.bmp",
            "decoded/data/image/text_menu.tlg",
          ]) {
            const row = await imageRow(page, id);
            if (row?.id !== id || row.state !== "applied" || row.staleReason)
              throw new Error(`Images reads ${id} as ${JSON.stringify(row)}.`);
          }
        },
      ],
    ],
  },
  "assistant-released": {
    description:
      "An Assistant-led project the assistant translated and wrote, but for one line its extractor missed, then played, that line translated through its extraction and injection once Text QA counted it never translated, reviewed with Text QA through the project helper, one correction applied, and played again before packaging; Progress holds QA at Final check until that playtest settles, the Playtest tab then reads Skipped for the game it could not play, its Patch phase shows the patch ZIP, and Release builds a clean game ZIP and saves the patch ZIP, with QA's correction and that line, where it suggests.",
    steps: () => [
      [
        "Open the game Assistant-led, the assistant translating, without image text",
        async (context) => {
          await assistantLed[0][1](context);
          const { page } = context;
          const project_id = (await page.call("workspace_snapshot")).application
            .project.id;
          const current = await page.call("translation_state", { project_id });
          await page.call("translation_save", {
            project_id,
            revision: current.revision,
            values: { ...current.options, include_images: false },
          });
        },
      ],
      assistantLed[1],
      [
        "The assistant translates all the text and writes it, but for one line its extractor misses",
        async ({ page, state }) => {
          await assistant(
            page,
            state,
            "organize",
            "--complete",
            "--miss",
            `Map001${missedLine}`,
          );
          const run = JSON.parse(await assistant(page, state, "translate"));
          if (run.status !== "complete")
            throw new Error(
              `Run ${run.id}: ${run.status}, ${run.message || ""}`,
            );
          await assistant(page, state, "write");
        },
      ],
      ...assistantQa,
      [
        "The Playtest tab reads the play the game could not have as skipped, the final check ended, as Progress does",
        async ({ page, state }) => {
          // The fixture game has no engine scripts to play, and its report
          // names no crash, so the final check settled without a play.
          await page.click("Playtest");
          await until(
            "the Playtest tab to read Skipped, ending the final check",
            async () => {
              const shown = await playtestPanel(page);
              if (
                shown?.state === "skipped" &&
                shown.description.includes("final check ends without a play")
              )
                return true;
              // The timeout names what it read last.
              throw new Error(`It reads ${JSON.stringify(shown)}.`);
            },
          );
          await page.shot(
            path.join(state.work, "logs", "playtest-skipped.png"),
          );
          await page.click("Progress");
        },
      ],
      [
        "The assistant packages the patch",
        async ({ page, state }) =>
          console.log(
            `\n  ${(await assistant(page, state, "package")).trim()}`,
          ),
      ],
      [
        "Progress shows the patch; Release builds a clean game ZIP and the patch ZIP, which holds QA's correction",
        async ({ page, state }) => {
          await page.waitText("Patch ZIP\nDone");
          await page.locate("Open folder");
          await page.click("Release");
          const [folder, name] = await page.evaluate(
            `[document.querySelector("[aria-label='Save in']").value, document.querySelector(".guided-package-fields input").value]`,
          );
          // Progress showed the assistant's patch, so each ZIP's own file
          // says its build is done.
          const built = (archive, kind) =>
            until(
              `the ${kind} ZIP`,
              async () =>
                fs.existsSync(path.join(folder, archive)) &&
                !(await page.call("workspace_snapshot")).application.running &&
                (await page.text()).includes(`Last saved ${kind} ZIP\nDone`),
              5 * 60_000,
            );
          await page.click("Build clean game ZIP");
          await built(name, "game");
          const actors = path.join(
            contentFolder([], state.game),
            "data/Actors.json",
          );
          const written = fs.readFileSync(actors);
          const game = new Map(
            [...entries(fs.readFileSync(path.join(folder, name)))].map(
              (entry) => [entry.path, entry.data],
            ),
          );
          const top = name.replace(/\.zip$/, "");
          if (!game.get(`${top}/data/Actors.json`)?.equals(written))
            throw new Error(
              "The clean game ZIP lacks the translated Actors.json.",
            );
          const own = [...game.keys()].filter((entry) =>
            entry.startsWith(`${top}/.`),
          );
          if (own.length)
            throw new Error(`The clean game ZIP holds ${own.join(", ")}.`);
          await page.click(/^Patch ZIP/);
          const patchName = await page.evaluate(
            `document.querySelector(".guided-package-fields input").value`,
          );
          await page.click("Review & build patch ZIP");
          await page.click(/^(Replace & build|Build) patch ZIP$/);
          await built(patchName, "patch");
          const patch = new Map(
            [...entries(fs.readFileSync(path.join(folder, patchName)))].map(
              (entry) => [entry.path, entry.data],
            ),
          );
          if (!patch.get("data/Actors.json")?.equals(written))
            throw new Error("The patch ZIP lacks the translated Actors.json.");
          const corrected = [...patch].filter(
            ([entry, data]) =>
              entry.endsWith(".json") && data.includes(qaCorrection),
          );
          if (
            !corrected.length ||
            corrected.some(
              ([entry, data]) =>
                !data.equals(fs.readFileSync(path.join(state.game, entry))),
            )
          )
            throw new Error("The patch ZIP lacks Text QA's correction.");
          // The line QA sent back to extraction, as the game holds it.
          const map = patch.get("data/Map001.json");
          const shown = JSON.parse(map || "{}")
            .events?.[1]?.pages[0].list.filter(
              (command) => command.code === 401,
            )
            .map((command) => command.parameters[0]);
          if (
            !map?.equals(
              fs.readFileSync(
                path.join(contentFolder([], state.game), "data/Map001.json"),
              ),
            ) ||
            !shown.length ||
            shown.some((line) => /[぀-ヿ一-鿿]/.test(line))
          )
            throw new Error(
              "The patch ZIP lacks the line Text QA counted never translated.",
            );
          console.log(
            `\n  Clean game ZIP: ${game.size} entries; patch ZIP: ${patch.size}`,
          );
        },
      ],
    ],
  },
  "assistant-written": {
    description:
      "An Assistant-led project the assistant translated whole and wrote into the game, its choice labels and help markers kept in Japanese, its lines of punctuation alone written in English form without a request, and its actor's codes shown to it as her name and written back as codes.",
    game: "choice-help+unsent-lines+name-codes",
    steps: () => [
      ...assistantLed.slice(0, 2),
      assistantWrite,
      unsentWritten,
      nameCodesWritten,
    ],
  },
  "assistant-checked": {
    description:
      "assistant-written on the TyranoScript game, which Text QA can't read: qa --check lists its two forest lines missing the glossary's name and its inn price's changed number; the assistant corrects two through correction receipts, answers the third and writes the game again, and no hit is open.",
    game: "tyrano",
    steps: () => [
      ...assistantLed.slice(0, 2),
      assistantWrite,
      [
        "The assistant checks its translations with qa --check, corrects or answers each hit and writes the game again",
        async ({ page, state }) => {
          const { first, second } = JSON.parse(
            await assistant(page, state, "check"),
          );
          console.log(
            `\n  qa --check: ${first.open} open (${Object.entries(first.rules)
              .map(([rule, count]) => `${rule} ${count}`)
              .join(
                ", ",
              )}), then ${second.open} open and ${second.answered} answered`,
          );
          const written = fs.readFileSync(
            path.join(state.game, "data/scenario/first.ks"),
            "utf8",
          );
          for (const line of [
            "Welcome to the Elven Woods.[p]",
            "The inn costs 100 gold.[p]",
          ])
            if (!written.includes(line))
              throw new Error(`first.ks lacks the corrected line ${line}`);
        },
      ],
    ],
  },
  "assistant-updated": {
    description:
      "assistant-written, then version 1.1 brought in and applied under Checkpoints and its post-update task copied, which continues the starting prompt's steps from census in the project's mode and language pair.",
    game: "choice-help",
    steps: () => [
      ...assistantLed.slice(0, 2),
      assistantWrite,
      ...updateGame(),
      assistantUpdate,
    ],
  },
  "assistant-reorganized": {
    description:
      "An Assistant-led Live API project on the collapsed-line game with a long scene: all its text organized, approved and translated, each later part of the split scene sent with the English the part before it got, then a glossary entry added and the text organized again, whose estimate quotes only the lines the run kept in Japanese.",
    game: "collapsed-line+long-scene",
    steps: () => reorganized,
  },
  "batch-waiting": {
    description:
      "The database submitted as a Batch the stand-in holds at the provider; provider '{\"hold\":false}' releases it.",
    steps: () => [open, ...setup, ...batch],
  },
  "batch-queued": {
    description:
      "batch-waiting, then a copy of the game Assistant-led whose API Batch on the same OpenAI connection, with a small Batch token allowance, waits for capacity unsent until the held Batch is released, then is sent and completes.",
    steps: () => [open, ...setup, batch[0], ...queuedBatch],
  },
  repriced: {
    description:
      "A whole-game estimate in a Guided game, then a copy Assistant-led whose API Batch estimate waits on Progress, both on the OpenAI preset, saved again as a release before a pricing fix saves them: first as counts DazedTL can't price again, which must ask to be estimated again and offer no Approve, then at three times today's price, which each must show at today's price, Approve freezing the price shown.",
    steps: () => [open, ...setup, batch[0], ...repriced],
  },
  upgraded: {
    description:
      "Translated and applied by the previous release, then opened in this version, as after an update.",
    from: "previous",
    upgrade: true,
    steps: () => [open, ...setup, ...translateAll],
  },
  paged: {
    description:
      "A long English message translated and applied, then the Line widths narrowed so it pages; the game must show every word.",
    game: "long-dialogue",
    steps: () => [open, ...setup, ...translateAll, narrowWidths],
  },
  shared: {
    description:
      "Translated and applied with Guided steps and First-line names on, exported from the Project page as a translation file whose first-row nameplate is a line apart from its speech, the speech then edited onto one long row, and imported into an untranslated copy of the game, where Translate applies it: the copy shows the same text, the nameplate on its own row.",
    game: "first-line-speaker",
    steps: () => [
      open,
      ...setup,
      ["Turn on First-line names", ({ page }) => firstLineNames(page)],
      ...translateAll,
      ...sharedFile,
    ],
  },
  manual: {
    description:
      "A game translated Manually: a stand-in for the user's own extractor writes its text into a translation file, which Text loads and a Live run translates, its own injector writes the export into the game, and the Project page imports a translation edited by hand.",
    steps: () => manualLed,
  },
  playtested: {
    description:
      "Translated and applied, then played by the release playtest, which prints what it found.",
    game: "choice-help+hud+playable",
    steps: () => [open, ...setup, ...translateAll, playtest],
  },
};
