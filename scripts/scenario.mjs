// Builds a ready-made test scenario in a scratch folder, so reproducing a bug
// starts from a known state in minutes: a scratch profile, workspace and game
// copy, never the user's. See "Test scenarios" in docs/development.md.
//
//   node scripts/scenario.mjs <scenario> [--game <variants>] [--from <ref>] [--app] [--work <dir>]
//   node scripts/scenario.mjs list
//   node scripts/scenario.mjs app|stop|clean --work <dir>
//   node scripts/scenario.mjs provider --work <dir> '<mode JSON>'
//   node scripts/scenario.mjs drive --work <dir> text|click|click-prefix|call|eval|shot ...
//   node scripts/scenario.mjs live [e2e.mjs options]
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { root, python } from "./dependencies.mjs";
import { Page, until, message } from "./testkit/cdp.mjs";
import { freePort, startApp, stopApp, running } from "./testkit/app.mjs";
import { startDisplay, stopGroup, virtualDisplay } from "./testkit/display.mjs";
import { gameName, makeGame, variants } from "./testkit/games.mjs";
import { scenarios } from "./testkit/scenarios.mjs";
import { checkout, previousRelease } from "./testkit/checkout.mjs";

const args = process.argv.slice(2);
const option = (name) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : undefined;
};
const flag = (name) => args.includes(name);
const positional = args.filter(
  (value, index) =>
    !value.startsWith("--") &&
    !["--work", "--game", "--from"].includes(args[index - 1]),
);
const command = positional[0];

/** The state a built scenario keeps in its folder, for later commands. */
const stateFile = (work) => path.join(work, "scenario.json");
function readState(work) {
  if (!work) throw new Error("Name the scenario folder with --work <dir>.");
  const file = stateFile(path.resolve(work));
  if (!fs.existsSync(file)) throw new Error(`${work} holds no scenario.`);
  return JSON.parse(fs.readFileSync(file, "utf8"));
}
const writeState = (state) =>
  fs.writeFileSync(stateFile(state.work), JSON.stringify(state, null, 2));

const alive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
};

/** Starts the scenario's stand-in provider on its saved port, unless it runs. */
async function startProvider(state) {
  if (state.provider.pid && alive(state.provider.pid)) return;
  const log = fs.openSync(path.join(state.work, "logs/provider.log"), "a");
  const child = spawn(
    process.execPath,
    [
      path.join(root, "scripts/testkit/provider.mjs"),
      "--folder",
      path.join(state.work, "provider"),
      "--port",
      String(state.provider.port),
    ],
    { detached: true, stdio: ["ignore", log, log] },
  );
  fs.closeSync(log);
  child.unref();
  state.provider.pid = child.pid;
  writeState(state);
  await until(
    "the stand-in provider",
    async () => (await fetch(`${state.provider.url}/models`)).ok,
    10_000,
  );
}

/**
 * A display for the app on Linux: a private KWin, or the Xvfb display CI's
 * xvfb-run offers. Never the desktop's, so the app's window stays off it.
 */
async function startScreen(state) {
  if (process.platform !== "linux") return {};
  if (state.display?.group && alive(state.display.group))
    return state.display.env;
  try {
    state.display = await startDisplay({
      name: `dazedtl-${path.basename(state.work)}`,
      log: path.join(state.work, "logs/display.log"),
    });
  } catch (error) {
    state.display = virtualDisplay();
    if (!state.display)
      throw new Error(
        `${message(error)} Without it the app would open on your desktop, so it does not start.`,
      );
    console.log(
      `Using Xvfb DISPLAY ${state.display.env.DISPLAY}: ${message(error)}`,
    );
  }
  writeState(state);
  return state.display.env;
}

/** Starts the scenario's app and connects to its window. */
async function openApp(state) {
  await startProvider(state);
  const env = await startScreen(state);
  state.app = {
    debug: await freePort(),
    inspect: await freePort(),
  };
  state.app.pid = await startApp({
    root: state.root,
    profile: state.profile,
    tag: state.tag,
    log: path.join(state.work, "logs/app.log"),
    debug: state.app.debug,
    inspect: state.app.inspect,
    env: {
      ...env,
      // The OpenAI preset reaches the stand-in, which offers Batch offline;
      // the OpenAI SDK's own default address follows it.
      DAZEDTL_TEST_OPENAI_ENDPOINT: `${state.provider.url.replace(/\/v1$/, "")}/api.openai.com/v1`,
      OPENAI_BASE_URL: `${state.provider.url.replace(/\/v1$/, "")}/api.openai.com/v1`,
      ...state.env,
    },
  });
  writeState(state);
  const page = await Page.connect(state.app.debug, { root: state.root });
  await page.waitText("App ready");
  return page;
}

async function stopAll(state) {
  await stopApp(state.tag, state.app?.pid);
  if (state.provider.pid && alive(state.provider.pid))
    process.kill(state.provider.pid, "SIGTERM");
  state.provider.pid = 0;
  if (state.display?.group) await stopGroup(state.display.group);
  state.display = null;
  state.app = null;
  writeState(state);
}

/** How a session reaches the running scenario. */
async function describe(state, page) {
  const lines = [
    `Scenario ${state.name} in ${state.work}${state.from && state.root !== root ? `, run by ${state.from}` : ""}`,
    `  game:     ${state.game}`,
    `  profile:  ${state.profile}`,
    `  provider: ${state.provider.url} (mode file ${path.join(state.work, "provider/mode.json")})`,
  ];
  if (page) {
    const project = (await page.call("workspace_snapshot")).application.project;
    lines.push(
      `  display:  ${state.display?.env?.DISPLAY || "the desktop"}`,
      `  CDP ${state.app.debug}, inspector ${state.app.inspect}`,
      "Drive it:",
      `  node scripts/scenario.mjs drive --work ${state.work} text`,
      `  node scripts/scenario.mjs drive --work ${state.work} click "<accessible name>"`,
      `  node scripts/scenario.mjs drive --work ${state.work} click-prefix "<start of an accessible name>"`,
      `  node scripts/scenario.mjs drive --work ${state.work} call <method> '<params JSON>'`,
      `  node scripts/scenario.mjs drive --work ${state.work} shot <file.png>`,
      "  or import { Page } from scripts/testkit/cdp.mjs and Page.connect(<CDP port>, { root }).",
    );
    if (project)
      lines.push(
        "The project helper, as an assistant's task runs it:",
        `  ${python} ${path.join(state.root, "scripts/project.py")} --workspace ${path.join(state.profile, "workspace")} --project ${project.id} <command>`,
      );
  } else
    lines.push(
      `Open the app: node scripts/scenario.mjs app --work ${state.work}`,
    );
  lines.push(`Clean up: node scripts/scenario.mjs clean --work ${state.work}`);
  console.log(lines.join("\n"));
}

async function build(name) {
  const scenario = scenarios[name];
  if (!scenario)
    throw new Error(
      `No scenario named ${name}; node scripts/scenario.mjs list shows them.`,
    );
  const work = path.resolve(
    option("--work") ||
      path.join(
        os.tmpdir(),
        "dazedtl-scenarios",
        `${name}-${crypto.randomBytes(3).toString("hex")}`,
      ),
  );
  fs.mkdirSync(work, { recursive: true });
  if (fs.readdirSync(work).length)
    throw new Error(`Choose an empty folder; ${work} has files.`);
  const started = Date.now();
  const providerPort = await freePort();
  // An earlier version builds the scenario when asked, or when the scenario
  // is about what that version left behind.
  const from =
    option("--from") ||
    (scenario.from === "previous" ? previousRelease() : undefined);
  const version = from ? checkout(from) : { root, env: {} };
  const state = {
    name,
    work,
    root: version.root,
    env: version.env,
    from: from || null,
    tag: `scenario-${crypto.randomBytes(6).toString("hex")}`,
    game: "",
    profile: path.join(work, "profile"),
    provider: {
      port: providerPort,
      url: `http://127.0.0.1:${providerPort}/v1`,
      pid: 0,
    },
    variants: (option("--game") || scenario.game || "mz").split("+"),
    app: null,
    display: null,
  };
  state.game = path.join(work, "ゲーム", gameName(state.variants));
  fs.mkdirSync(path.join(work, "logs"), { recursive: true });
  fs.mkdirSync(path.join(work, "provider"), { recursive: true });
  writeState(state);
  const mode = await makeGame(state.variants, state.game);
  if (Object.keys(mode).length)
    fs.writeFileSync(
      path.join(work, "provider/mode.json"),
      JSON.stringify(mode),
    );
  let page;
  // A build stopped from outside stops what it started.
  for (const signal of ["SIGINT", "SIGTERM"])
    process.once(signal, () => {
      console.error(`\nStopped; ending the scenario's processes.`);
      void stopAll(state).finally(() => process.exit(1));
    });
  try {
    const steps = scenario.steps();
    if (steps.length || flag("--app")) page = await openApp(state);
    for (const [label, run] of steps) {
      const at = Date.now();
      process.stdout.write(`- ${label} … `);
      await run({ page, state });
      console.log(`${((Date.now() - at) / 1000).toFixed(1)} s`);
    }
    if (scenario.upgrade) {
      // This version opens what the earlier one left, as after an update.
      page.close();
      page = undefined;
      await stopApp(state.tag, state.app?.pid);
      Object.assign(state, { root, env: {} });
      const at = Date.now();
      process.stdout.write(`- Open it in this version … `);
      page = await openApp(state);
      await page.waitText(path.basename(state.game));
      console.log(`${((Date.now() - at) / 1000).toFixed(1)} s`);
    }
    if (!flag("--app")) {
      page?.close();
      page = undefined;
      await stopAll(state);
    }
    console.log(`Built in ${((Date.now() - started) / 1000).toFixed(1)} s.`);
    await describe(state, page);
  } catch (error) {
    if (page)
      try {
        await page.shot(path.join(work, "logs/failure.png"));
        fs.writeFileSync(path.join(work, "logs/window.txt"), await page.text());
      } catch {
        // The window may be gone.
      }
    console.error(
      `\nThe scenario could not be built: ${message(error)}\nLogs: ${path.join(work, "logs")}`,
    );
    await stopAll(state);
    process.exitCode = 1;
  } finally {
    page?.close();
  }
}

async function drive(state) {
  const [action, ...rest] = positional.slice(1);
  if (!state.app || !running(state.tag).length)
    throw new Error(
      `The app is not running; node scripts/scenario.mjs app --work ${state.work}.`,
    );
  const page = await Page.connect(state.app.debug, { root: state.root });
  try {
    if (action === "text") console.log(await page.text());
    else if (action === "click") await page.click(rest[0], 10_000);
    else if (action === "click-prefix")
      // For names that end in something that varies, such as a History row's date.
      await page.click(
        new RegExp(`^${rest[0].replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`),
        10_000,
      );
    else if (action === "call")
      console.log(
        JSON.stringify(
          await page.call(rest[0], JSON.parse(rest[1] || "{}")),
          null,
          2,
        ),
      );
    else if (action === "eval")
      console.log(JSON.stringify(await page.evaluate(rest[0]), null, 2));
    else if (action === "shot") await page.shot(path.resolve(rest[0]));
    else throw new Error("Drive with text, click, call, eval or shot.");
  } finally {
    page.close();
  }
}

try {
  if (!command || command === "list") {
    for (const [name, scenario] of Object.entries(scenarios))
      console.log(`${name.padEnd(16)} ${scenario.description}`);
    console.log("\nGame variants, joined with + after --game:");
    for (const [name, description] of Object.entries(variants))
      console.log(`${name.padEnd(16)} ${description}`);
  } else if (command === "app") {
    const state = readState(option("--work"));
    const page = await openApp(state);
    await describe(state, page);
    page.close();
  } else if (command === "stop") await stopAll(readState(option("--work")));
  else if (command === "clean") {
    const state = readState(option("--work"));
    await stopAll(state);
    fs.rmSync(state.work, { recursive: true, force: true });
    console.log(`Removed ${state.work}.`);
  } else if (command === "provider") {
    const state = readState(option("--work"));
    const mode = JSON.parse(positional[1] || "{}");
    fs.writeFileSync(
      path.join(state.work, "provider/mode.json"),
      JSON.stringify(mode),
    );
    console.log(`The stand-in now answers with ${JSON.stringify(mode)}.`);
  } else if (command === "drive") await drive(readState(option("--work")));
  else if (command === "live") {
    // The live test in a private display of its own, so its window stays off
    // the desktop.
    const display =
      process.platform === "linux"
        ? await startDisplay({
            name: `dazedtl-live-${crypto.randomBytes(3).toString("hex")}`,
            log: path.join(os.tmpdir(), "dazedtl-live-display.log"),
          })
        : undefined;
    try {
      const result = spawnSync(
        process.execPath,
        [path.join(root, "scripts/e2e.mjs"), ...args.slice(1)],
        { stdio: "inherit", env: { ...process.env, ...display?.env } },
      );
      process.exitCode = result.status ?? 1;
    } finally {
      if (display) await stopGroup(display.group);
    }
  } else await build(command);
} catch (error) {
  console.error(message(error));
  process.exitCode = 1;
}
