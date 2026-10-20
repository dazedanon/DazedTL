// The steps of a Guided translation as a user takes them, shared by the live
// test and test scenarios. Each drives the window with clicks; only what a
// user does in a native dialog or with their clipboard goes another way.
import { Page, until } from "./cdp.mjs";
import { model } from "./provider.mjs";

/**
 * Opens `game` from the start screen and chooses a method. The folder
 * dialog is native, so it answers through the main process the way a user's
 * choice would.
 * @param {Page} page
 * @param {{ root: string, inspect: number, game: string }} options
 */
export async function openGame(
  page,
  { root, inspect, game, method = "Guided steps" },
) {
  const main = await Page.connect(inspect, { root, node: true });
  await main.evaluate(
    `process.mainModule.require("electron").dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [${JSON.stringify(game)}] })`,
  );
  main.close();
  await page.click("Open a game");
  if (method !== "Guided steps") await page.click(new RegExp(`^${method}`));
  await page.click(`Start with ${method}`);
  if (method === "Guided steps") await page.waitText("Set up this game");
}

/** Sets up the open game as untranslated, with its version. */
export async function setUp(page, version = "1.0") {
  await page.type("#guided-version", version);
  await page.click("This game is untranslated");
  await page.click("Set up this game");
  await page.waitText("Setup complete.", 5 * 60_000);
}

/**
 * Saves a connection to the stand-in provider at `url` with free rates and
 * checks it, as Settings does. With provider "openai", it saves the OpenAI
 * preset, which offers Batch; the app must run with
 * DAZEDTL_TEST_OPENAI_ENDPOINT naming the stand-in, as scenario apps do.
 * @param {Page} page
 */
export async function connect(page, url, provider = "custom") {
  const saved = await page.call("settings_get");
  const name = provider === "custom" ? "Stand-in" : "Stand-in OpenAI";
  // A profile that has one already, such as after an update, keeps it.
  const earlier = saved.connections.find((item) => item.name === name);
  let settings = await page.call("connection_save", {
    revision: saved.revision,
    ...(earlier && { connection_id: earlier.id }),
    provider,
    name,
    secret: "stand-in-key",
    endpoint: url,
    protocol: "openai",
    organization: "",
    keyless: false,
    reuse_secret: false,
  });
  const connection = settings.activeConnectionId;
  settings = await page.call("settings_save", {
    revision: settings.revision,
    connection_id: connection,
    values: { language: "English", model },
    model_options: {
      [model]: {
        entriesPerRequest: null,
        pricing: "custom",
        inputRate: 0,
        outputRate: 0,
      },
    },
  });
  settings = await page.call("connection_check", {
    revision: settings.revision,
    connection_id: connection,
  });
  const check = settings.connections.find(
    (item) => item.id === connection,
  ).check;
  if (!["reachable", "verified"].includes(check.status))
    throw new Error(`Connection check: ${check.message}`);
}

/**
 * Runs one Guided translation task live: estimate, approve, wait for the run.
 * With `failed`, a run that fails, as one with lines the provider refuses
 * does, ends the step too. Returns how the run ended.
 * @param {Page} page
 * @param {string} task
 */
export async function translateTask(page, task, { failed = false } = {}) {
  await page.click(task);
  // A task whose files hold no line count yet, such as an Ace game's, starts
  // with none selected.
  if (/(^|\n)0 selected/.test(await page.text()))
    await page.click("Select all");
  await page.click("Live");
  await page.click("Translate");
  await page.click("Start Live translation", 5 * 60_000);
  // "Run finished." alone, or with what it saved and what failed.
  const ending = failed
    ? /Run finished\b|The last run failed/
    : /Run finished\.(?! ·)/;
  return until(
    `${task}'s run to end`,
    async () => ending.exec(await page.text())?.[0],
    5 * 60_000,
  );
}

/**
 * Applies the task's finished translation and waits until its files hold it
 * (`check`) and Apply's follow-up work ends.
 * @param {Page} page
 * @param {string} task
 * @param {() => unknown} [check]
 */
export async function applyTask(page, task, check) {
  // Another task's apply must not confirm this one's.
  if ((await page.text()).includes("Saved translations applied."))
    throw new Error(`${task} reports applied translations before applying.`);
  await page.click(/^Apply \(\d+\)$/);
  await page.click("Apply reviewed files");
  await page.waitText("Saved translations applied.");
  if (check) await until(`${task} to reach the game files`, check);
  // Apply's own follow-up work runs on after the files change, and the app
  // refuses the next action until it ends.
  await page.idle();
}
