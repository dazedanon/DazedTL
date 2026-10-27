// The ready-made scenarios scripts/scenario.mjs builds. Each names its steps
// as a user takes them; a scenario that continues another starts with its
// steps.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { python } from "../dependencies.mjs";
import { until } from "./cdp.mjs";
import { contentFolder, gameName, makeRelease, release } from "./games.mjs";
import { translated } from "./provider.mjs";
import {
  chooseFolder,
  connect,
  openGame,
  setUp,
  translateTask,
  applyTask,
  buildPatch,
} from "./journey.mjs";

/** Runs a Python script of the scenario's checkout, as an assistant's shell does. */
const run = (state, script, ...args) =>
  execFileSync(
    state.env?.DAZEDTL_PYTHON || python,
    ["-X", "utf8", path.join(state.root, script), ...args],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );

/** Runs the project helper with `args` and reads its JSON reply. */
async function helper(page, state, ...args) {
  const project = (await page.call("workspace_snapshot")).application.project;
  return JSON.parse(
    run(
      state,
      "scripts/project.py",
      "--workspace",
      path.join(state.profile, "workspace"),
      "--project",
      project.id,
      ...args,
    ),
  );
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
    execFileSync(
      state.env?.DAZEDTL_PYTHON || python,
      [
        "-X",
        "utf8",
        "-c",
        "import json, sys; sys.path.insert(0, sys.argv[1]); " +
          "from util.rpgmaker_rewrap import visible_width; " +
          "print(json.dumps([visible_width(row) for row in json.loads(sys.argv[2])]))",
        path.join(state.root, "backend/dazedtl/engine"),
        JSON.stringify(rows),
      ],
      { encoding: "utf8" },
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

const qa = [
  "Review and apply Text QA as an assistant does",
  async ({ page, state }) => {
    const prepared = await helper(page, state, "qa", "--prepare");
    // The reviewer of the checkout the app runs from, whose engine and QA
    // rules prepared the task.
    run(
      state,
      "scripts/testkit/qa_reviewer.py",
      prepared.task,
      path.join(state.work, "qa-results"),
    );
    const applied = await helper(page, state, "qa", "--apply");
    if (!applied.applied)
      throw new Error(`Text QA did not apply: ${applied.message}`);
    await page.idle();
  },
];

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
    execFileSync(
      state.env?.DAZEDTL_PYTHON || python,
      [
        "-X",
        "utf8",
        path.join(import.meta.dirname, "plugin_assistant.py"),
        task.request,
        "--game",
        state.game,
        "--helper-json",
        JSON.stringify([
          state.env?.DAZEDTL_PYTHON || python,
          "-X",
          "utf8",
          path.join(state.root, "scripts/project.py"),
          "--workspace",
          path.join(state.profile, "workspace"),
          "--project",
          project.id,
        ]),
      ],
      { encoding: "utf8" },
    );
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
    "Rename that folder and find it from the Project page",
    async ({ page, state }) => {
      const before = await projectView(page, state.game);
      const game = path.join(path.dirname(state.game), "Renamed");
      moveGame(state, game);
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
      await page.waitText("Waiting for provider results");
    },
  ],
];

/** Runs the scripted Assistant-led assistant's `step`. */
async function assistant(page, state, step, ...args) {
  const project = (await page.call("workspace_snapshot")).application.project;
  const command = [
    state.env?.DAZEDTL_PYTHON || python,
    "-X",
    "utf8",
    path.join(state.root, "scripts/project.py"),
    "--workspace",
    path.join(state.profile, "workspace"),
    "--project",
    project.id,
  ];
  return execFileSync(
    state.env?.DAZEDTL_PYTHON || python,
    [
      "-X",
      "utf8",
      path.join(import.meta.dirname, "assistant.py"),
      step,
      "--helper-json",
      JSON.stringify(command),
      "--game",
      state.game,
      ...args,
    ],
    { encoding: "utf8" },
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
      execFileSync(
        state.env?.DAZEDTL_PYTHON || python,
        [
          "-X",
          "utf8",
          path.join(import.meta.dirname, "stopped_update.py"),
          state.root,
          path.join(state.profile, "workspace"),
          preview.id,
        ],
        { encoding: "utf8" },
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
      "plugins-applied with a whole-game estimate and a Text QA task reviewing every line, then the game moved into a Game folder inside its own and opened there, then renamed and found from the Project page; each must keep the project, its estimates and its Text QA task unchanged.",
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
  "assistant-written": {
    description:
      "An Assistant-led project the assistant translated whole and wrote into the game, its choice labels and help markers kept in Japanese.",
    game: "choice-help",
    steps: () => [...assistantLed.slice(0, 2), assistantWrite],
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
  "batch-waiting": {
    description:
      "The database submitted as a Batch the stand-in holds at the provider; provider '{\"hold\":false}' releases it.",
    steps: () => [open, ...setup, ...batch],
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
  playtested: {
    description:
      "Translated and applied, then played by the release playtest, which prints what it found.",
    game: "choice-help+hud+playable",
    steps: () => [open, ...setup, ...translateAll, playtest],
  },
};
