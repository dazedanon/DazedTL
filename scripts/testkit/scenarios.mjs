// The ready-made scenarios scripts/scenario.mjs builds. Each names its steps
// as a user takes them; a scenario that continues another starts with its
// steps.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { python } from "../dependencies.mjs";
import { until } from "./cdp.mjs";
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
          /Translation could not start\n(.+)/.exec(await page.text())?.[1],
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
  playtested: {
    description:
      "Translated and applied, then played by the release playtest, which prints what it found.",
    game: "choice-help+hud+playable",
    steps: () => [open, ...setup, ...translateAll, playtest],
  },
};
