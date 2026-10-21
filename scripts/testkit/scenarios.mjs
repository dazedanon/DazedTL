// The ready-made scenarios scripts/scenario.mjs builds. Each names its steps
// as a user takes them; a scenario that continues another starts with its
// steps.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { python } from "../dependencies.mjs";
import { until } from "./cdp.mjs";
import { gameName, makeGame } from "./games.mjs";
import {
  connect,
  openGame,
  setUp,
  translateTask,
  applyTask,
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

const batch = [
  [
    "Connect the OpenAI preset, which reaches the stand-in",
    ({ page }) => connect(page, "", "openai"),
  ],
  [
    "Submit the database as a Batch the stand-in holds",
    async ({ page, state }) => {
      fs.writeFileSync(
        path.join(state.work, "provider/mode.json"),
        JSON.stringify({ hold: true }),
      );
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

const stoppedUpdate = [
  [
    "Open Checkpoints, the translation's Apply already its checkpoint",
    async ({ page }) => {
      await page.click("Project");
      await page.click("Checkpoints");
      await page.waitText("Start game update");
    },
  ],
  [
    "Bring in version 1.1, which changes a profile the translation changed",
    async ({ page, state }) => {
      if (state.variants[0] === "ace")
        throw new Error("The update changes the MZ game's Actors.json.");
      const release = path.join(
        state.work,
        "リリース 1.1",
        gameName(state.variants),
      );
      await makeGame(state.variants, release);
      const file = path.join(release, "data/Actors.json");
      const actors = JSON.parse(fs.readFileSync(file, "utf8"));
      actors[1].profile = "森の村に住む元気な女の子。\n伝説の杖を探している。";
      fs.writeFileSync(file, JSON.stringify(actors));
      await page.click("Start game update");
      // Typed, as a user may instead of choosing it in the folder dialog.
      await page.type("#update-official-folder", release);
      await page.waitText("Complete game");
      await page.type("#update-version", "1.1");
      await page.click("Prepare new release");
      await page.click("Preview changes", 5 * 60_000);
      await page.waitText("Apply update to 1.1", 5 * 60_000);
    },
  ],
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
  "qa-done": {
    description:
      "Translated and applied, then Text QA reviewed by a scripted assistant, one correction applied.",
    steps: () => [open, ...setup, ...translateAll, qa],
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
