// Starts DazedTL from a checkout with a scratch profile, for test scenarios:
// never the user's profile, with its own DevTools and inspector ports, and
// with every process it starts marked so they can be found and stopped
// without touching another session's app.
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { until } from "./cdp.mjs";

/** The environment variable every process of a scenario app carries. */
const marker = "DAZEDTL_SCENARIO";

export async function freePort() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = /** @type {net.AddressInfo} */ (server.address());
  await new Promise((resolve) => server.close(resolve));
  return port;
}

/**
 * The arguments that open a test app's window and main process to DevTools.
 * The app takes free ports itself and reports them, read back with
 * `reportedPorts`: a port chosen before it starts can be taken in between by
 * any process's connection, and an inspector that cannot listen leaves the
 * app running without one.
 */
export const debugArgs = ["--remote-debugging-port=0", "--inspect=0"];

/**
 * The DevTools and inspector ports an app started with `debugArgs` printed in
 * `output`, which holds that one start's output.
 * @param {string} output
 */
export function reportedPorts(output) {
  const port = (pattern) => Number(pattern.exec(output)?.[1] || 0);
  const ports = {
    debug: port(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//),
    inspect: port(/Debugger listening on ws:\/\/127\.0\.0\.1:(\d+)\//),
  };
  if (!ports.debug || !ports.inspect)
    throw new Error(
      `The app reported no DevTools or inspector port:\n${output.trim().split("\n").slice(-15).join("\n")}`,
    );
  return ports;
}

/** The Electron executable of the checkout at `root`. */
export function electronOf(root) {
  const require = createRequire(
    path.join(root, "app/node_modules/electron/package.json"),
  );
  return /** @type {string} */ (require("electron"));
}

/**
 * Builds the renderer of the checkout at `root` when its sources changed, as
 * START does.
 */
export async function ensureRenderer(root) {
  const build = path.join(root, "scripts/build.mjs");
  const { rendererStale, buildRenderer } = await import(
    pathToFileURL(build).href
  );
  if (rendererStale()) {
    console.log("Building the interface…");
    buildRenderer();
  }
}

/**
 * The variables of a scenario app: those of this process, plus `env`. Under a
 * test display on Linux the app also gets none of the desktop session it
 * could reach: its bus, audio and runtime folder, and a Wayland compositor
 * other than the one `env` names, so a sound or a notification a scenario
 * triggers stays off the user's desktop.
 * @param {NodeJS.ProcessEnv} base
 * @param {Record<string, string>} env
 * @param {string} platform
 */
export function appEnvironment(base, env, platform = process.platform) {
  const variables = { ...base };
  delete variables.ELECTRON_RUN_AS_NODE;
  if (platform === "linux" && env.DISPLAY)
    for (const name of Object.keys(variables))
      if (
        /^(DBUS_|XDG_RUNTIME_DIR$|XDG_SESSION_|WAYLAND_|PULSE_|PIPEWIRE_)/.test(
          name,
        )
      )
        delete variables[name];
  return { ...variables, ...env };
}

/**
 * Starts the app of the checkout at `root` on `profile` and waits for its
 * window. `tag` marks its processes; `env` adds variables such as a display.
 * Resolves its process and the DevTools and inspector ports it took.
 * @param {{ root: string, profile: string, tag: string, log: string,
 *   env?: Record<string, string>, args?: string[] }} options
 */
export async function startApp({
  root,
  profile,
  tag,
  log,
  env = {},
  args = [],
}) {
  if (running(tag).length)
    throw new Error(`The app of ${tag} is already running.`);
  await ensureRenderer(root);
  fs.mkdirSync(profile, { recursive: true });
  // A check that just ran keeps the app from offering a newer release.
  const updates = path.join(profile, "updates.json");
  if (!fs.existsSync(updates))
    fs.writeFileSync(
      updates,
      JSON.stringify({ checkedAt: new Date().toISOString() }),
    );
  const variables = appEnvironment(process.env, env);
  const key =
    Object.keys(variables).find((name) => name.toUpperCase() === "PATH") ||
    "PATH";
  // The backend checks plugin scripts with Node, as START provides it.
  variables[key] = [path.dirname(process.execPath), variables[key]].join(
    path.delimiter,
  );
  // The log keeps earlier starts' output; this start's follows it.
  const from = fs.existsSync(log) ? fs.statSync(log).size : 0;
  const started = () => fs.readFileSync(log).subarray(from).toString("utf8");
  const output = fs.openSync(log, "a");
  const isolated = env.DISPLAY && process.platform === "linux";
  const electron = [
    electronOf(root),
    path.join(root, "app"),
    ...debugArgs,
    ...(isolated ? ["--ozone-platform=x11", "--mute-audio"] : []),
    ...args,
  ];
  const child = spawn(
    // Its own session bus, where a desktop notification has nobody to show it.
    isolated ? "dbus-run-session" : electron[0],
    isolated ? ["--", ...electron] : electron.slice(1),
    {
      cwd: root,
      env: {
        ...variables,
        // Requests the backend and window make outside this machine go to a
        // proxy that is not there. Run workers start from a clean
        // environment without it, so the stand-in's address must reach them
        // through the run's own route, as DAZEDTL_TEST_OPENAI_ENDPOINT does.
        HTTP_PROXY: "http://127.0.0.1:9",
        HTTPS_PROXY: "http://127.0.0.1:9",
        ALL_PROXY: "http://127.0.0.1:9",
        NO_PROXY: "127.0.0.1,localhost",
        DAZEDTL_PROFILE: profile,
        DAZEDTL_CHECK_CONTRACTS: "1",
        DAZEDTL_LAUNCH_SIGNAL: "1",
        [marker]: tag,
      },
      detached: process.platform !== "win32",
      stdio: ["ignore", output, output],
    },
  );
  fs.closeSync(output);
  let exit = null;
  child.on("exit", (code) => (exit = code ?? 1));
  child.unref();
  await until(
    "the app window",
    () => exit !== null || started().includes("dazedtl:shown"),
    120_000,
  );
  if (exit !== null)
    throw new Error(
      `The app exited while starting:\n${started().trim().split("\n").slice(-15).join("\n")}`,
    );
  try {
    return { pid: child.pid, ...reportedPorts(started()) };
  } catch (error) {
    // An app nothing can drive is stopped rather than left holding the
    // profile.
    await stopApp(tag, child.pid);
    throw error;
  }
}

/** The processes of the scenario app tagged `tag`, its children included
 * (Linux only; Windows lists no other process's environment). */
export function running(tag) {
  if (process.platform === "win32") return [];
  const found = [];
  for (const name of fs.readdirSync("/proc")) {
    if (!/^\d+$/.test(name)) continue;
    try {
      const env = fs.readFileSync(`/proc/${name}/environ`, "utf8").split("\0");
      if (env.includes(`${marker}=${tag}`)) found.push(Number(name));
    } catch {
      // Exited, or another user's process.
    }
  }
  return found;
}

const kill = (pid, signal) => {
  try {
    process.kill(pid, signal);
  } catch {
    // Already gone.
  }
};

/** Whether any process is left in process group `group`. */
const groupAlive = (group) => {
  try {
    process.kill(-group, 0);
    return true;
  } catch {
    return false;
  }
};

/**
 * Closes the scenario app started as `pid` the way its window's close button
 * does, then ends whatever is left of it, and returns only once every process
 * of the app has exited, so its folder can be removed at once. Electron and
 * Chromium's own processes carry no `tag` that can be read (they are not
 * dumpable), so the app's process group, which `startApp` makes, counts too.
 */
export async function stopApp(tag, pid, timeout = 30_000) {
  if (process.platform === "win32") {
    if (pid)
      spawnSync("taskkill", ["/F", "/T", "/PID", String(pid)], {
        stdio: "ignore",
      });
    return;
  }
  const gone = () => !running(tag).length && !(pid && groupAlive(pid));
  if (gone()) return;
  if (pid) kill(pid, "SIGTERM");
  try {
    await until("the app to close", gone, timeout);
  } catch {
    for (const left of running(tag)) kill(left, "SIGKILL");
    if (pid) kill(-pid, "SIGKILL");
    await until("the app to end", gone, 10_000);
  }
}
