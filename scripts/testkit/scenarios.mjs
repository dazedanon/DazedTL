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
            text.includes("Saved translations applied.")) &&
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
    if (messageRows(state).every((row) => row.length <= 24))
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
    const words = `${await longMessage(state)}`;
    await until("the long message to page at the narrow widths", async () => {
      const rows = messageRows(state);
      return rows.length > 2 && rows.every((row) => row.length <= 24) && rows;
    });
    const shown = messageRows(state).join(" ").replace(/\s+/g, " ");
    if (!shown.includes(words))
      throw new Error(`The paged message lost words: ${shown}`);
  },
];

/** The traveler's message the stand-in's long mode writes, as English words. */
async function longMessage() {
  const { longText } = await import("./provider.mjs");
  return longText.slice(0, 40);
}

/** The rows of the traveler's message, its commands' lines split apart; a
 * paged message holds empty rows that fill its last page. */
/** The text rows of the traveler's message commands in the game's Map001. */
function messageRows(state) {
  const map = JSON.parse(
    fs.readFileSync(path.join(state.game, "data/Map001.json"), "utf8"),
  );
  const event = map.events.find((item) => item?.name === "旅人");
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
    // This checkout's reviewer, since the task names the engine that runs it.
    execFileSync(
      state.env?.DAZEDTL_PYTHON || python,
      [
        "-X",
        "utf8",
        path.join(import.meta.dirname, "qa_reviewer.py"),
        prepared.task,
        path.join(state.work, "qa-results"),
      ],
      { encoding: "utf8" },
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
      const done = (action) =>
        jobs.find((job) => job.action === action && job.status === "complete")
          .result;
      const stage = done("stage_update");
      // The app's Apply resolves conflicts at once; stopping before that is
      // what an update interrupted mid-apply leaves for Checkpoints.
      execFileSync(
        state.env?.DAZEDTL_PYTHON || python,
        [
          "-X",
          "utf8",
          path.join(import.meta.dirname, "stopped_update.py"),
          state.root,
          state.game,
          stage.official,
          stage.version,
          JSON.stringify(done("version_preview")),
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
        const review = text.slice(text.indexOf(heading) + heading.length);
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
        // The release changes a profile and describes an armor, and Set up's own
        // files read as changes too; every other translation stays.
        if (
          count("removed") ||
          review.includes("applying it removes them") ||
          files > 6 ||
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
  "assistant-led": {
    description:
      "An Assistant-led project, the assistant translating itself: set up, text organized, the first request translated and the rest waiting.",
    steps: () => assistantLed,
  },
  "assistant-written": {
    description:
      "An Assistant-led project the assistant translated whole and wrote into the game, its choice labels and help markers kept in Japanese.",
    game: "choice-help",
    steps: () => [...assistantLed.slice(0, 2), assistantWrite],
  },
  "batch-waiting": {
    description:
      "The database submitted as a Batch the stand-in holds at the provider; provider '{}' releases it.",
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
