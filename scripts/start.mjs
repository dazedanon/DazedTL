// Starts DazedTL from this folder: brings the install up to date, rebuilds a
// stale interface and opens the app. START.bat and START.sh pass --detach, so
// their console closes once the window opens; development runs stay attached.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { setTimeout as delay } from "node:timers/promises";
import {
  app,
  root,
  runtime,
  dependencies,
  bundledGit,
} from "./dependencies.mjs";
import { ensureSetup, readState, writeState } from "./setup.mjs";
import { shortcuts, desktopEntry } from "./shortcuts.mjs";
import { applyPending } from "./update.mjs";

const args = process.argv.slice(2);
const detach = args.includes("--detach");
const after = args.indexOf("--after");
const waitFor = after >= 0 ? Number(args[after + 1]) : 0;
const forward = args.filter(
  (value, index) =>
    value !== "--detach" && index !== after && index !== after + 1,
);

const alive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return /** @type {NodeJS.ErrnoException} */ (error).code === "EPERM";
  }
};

/**
 * One launcher works on this folder at a time; a dead holder's lock is stale.
 * Returns the function that releases the lock, or null when another holds it.
 */
function lock() {
  const file = path.join(runtime, "launcher.lock");
  fs.mkdirSync(runtime, { recursive: true });
  // Only this launcher's own lock is removed, never the next launcher's.
  const release = () => {
    try {
      if (fs.readFileSync(file, "utf8") === String(process.pid))
        fs.rmSync(file, { force: true });
    } catch {
      // Already released.
    }
  };
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      fs.writeFileSync(file, String(process.pid), { flag: "wx" });
      process.on("exit", release);
      return release;
    } catch {
      const holder = Number(fs.readFileSync(file, "utf8")) || 0;
      if (holder && alive(holder)) return null;
      fs.rmSync(file, { force: true });
    }
  }
  return null;
}

/**
 * Hands over to the START launcher that an update just installed, so a
 * release's own setup and runtime pins apply from its first start.
 */
function restart() {
  const result =
    process.platform === "win32"
      ? spawnSync(
          process.env.ComSpec || "cmd.exe",
          [
            "/d",
            "/s",
            "/c",
            `""${path.join(root, "START.bat")}" ${forward.join(" ")}"`,
          ],
          { cwd: root, stdio: "inherit", windowsVerbatimArguments: true },
        )
      : spawnSync("bash", [path.join(root, "START.sh"), ...forward], {
          cwd: root,
          stdio: "inherit",
        });
  if (result.error) throw result.error;
  // The new launcher has already shown any failure and waited for the user.
  return 0;
}

// Rebuild when renderer inputs changed since the last build, such as after an
// update; the backend refuses a renderer built from older contracts.
function rendererStale() {
  const built = fs.statSync(path.join(app, "dist/index.html"), {
    throwIfNoEntry: false,
  })?.mtimeMs;
  const inputs = [
    ...fs.globSync("app/src/**", { cwd: root }),
    "app/index.html",
    "app/package-lock.json",
    "app/tsconfig.json",
    "app/vite.config.ts",
    "backend/dazedtl/api/protocol.json",
  ];
  return (
    built === undefined ||
    inputs.some((file) => fs.statSync(path.join(root, file)).mtimeMs > built)
  );
}

/**
 * Ubuntu 24.04 and later block the browser sandbox of apps without an AppArmor
 * profile, so Electron would exit at once. Returns the one-time fix, if needed.
 */
function sandboxFix(electron) {
  if (process.platform !== "linux") return "";
  try {
    if (
      fs
        .readFileSync("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
        .toString()
        .trim() !== "1"
    )
      return "";
  } catch {
    return "";
  }
  const sandbox = fs.statSync(
    path.join(path.dirname(electron), "chrome-sandbox"),
    {
      throwIfNoEntry: false,
    },
  );
  if (sandbox && sandbox.uid === 0 && sandbox.mode & 0o4000) return "";
  const name = `dazedtl-${crypto.createHash("sha256").update(electron).digest("hex").slice(0, 12)}`;
  if (fs.existsSync(`/etc/apparmor.d/${name}`)) return "";
  const profile = path.join(runtime, name);
  fs.writeFileSync(
    profile,
    [
      "abi <abi/4.0>,",
      "include <tunables/global>",
      "",
      `profile ${name} "${electron}" flags=(unconfined) {`,
      "  userns,",
      `  include if exists <local/${name}>`,
      "}",
      "",
    ].join("\n"),
  );
  return [
    "This system only lets apps with an AppArmor profile use the browser sandbox.",
    "Run this once to allow DazedTL, then start it again:",
    "",
    `  sudo install -m 644 "${profile}" /etc/apparmor.d/${name} && sudo apparmor_parser -r /etc/apparmor.d/${name}`,
  ].join("\n");
}

/** Shows a failure where the user will see it when no terminal is attached. */
function alert(message) {
  if (process.stdin.isTTY || process.platform === "win32") return;
  const tools =
    process.platform === "darwin"
      ? [
          [
            "osascript",
            [
              "-e",
              `display alert "DazedTL could not start" message ${JSON.stringify(message)}`,
            ],
          ],
        ]
      : [
          ["kdialog", ["--title", "DazedTL", "--error", message]],
          ["zenity", ["--error", "--title=DazedTL", `--text=${message}`]],
          ["notify-send", ["DazedTL could not start", message]],
        ];
  for (const [command, values] of tools)
    if (spawnSync(command, values, { stdio: "ignore" }).status === 0) return;
}

async function launch() {
  if (waitFor) {
    // The app that asked for this restart must be gone before files change.
    for (let tries = 0; tries < 300 && alive(waitFor); tries++)
      await delay(200);
  }
  const release = lock();
  if (!release) {
    console.log("DazedTL is already starting.");
    return 0;
  }
  // Updates swap files before anything reads them; the app reports the
  // outcome. This launcher is the old version's code, so the new one takes
  // over from here.
  const swap = applyPending();
  if (swap?.ok) {
    console.log(`DazedTL is now version ${swap.version}.`);
    release();
    return restart();
  }
  if (swap)
    console.error(
      `The update to ${swap.version} could not be installed: ${swap.message}`,
    );
  const state = readState();
  await ensureSetup({
    mode:
      state.mode || (fs.existsSync(path.join(root, ".git")) ? "dev" : "user"),
  });
  if (rendererStale()) {
    console.log("Building the interface…");
    const { buildRenderer } = await import("./build.mjs");
    buildRenderer();
  }
  const current = readState();
  if (current.mode === "user") {
    shortcuts(current);
    writeState(current);
  }

  const require = createRequire(
    path.join(dependencies(), "electron/package.json"),
  );
  const electron = require("electron");
  const fix = sandboxFix(electron);
  if (fix) throw new Error(fix);
  const env = { ...process.env, CHROME_DESKTOP: desktopEntry };
  delete env.ELECTRON_RUN_AS_NODE;
  // The backend validates plugin scripts with Node and keeps projects in Git;
  // the launcher's Node and the bundled Git are there even when the system has
  // neither.
  const key =
    Object.keys(env).find((name) => name.toUpperCase() === "PATH") || "PATH";
  env[key] = [path.dirname(process.execPath), bundledGit()?.bin, env[key]]
    .filter(Boolean)
    .join(path.delimiter);
  if (!detach) {
    const child = spawn(electron, [app, ...forward], {
      cwd: root,
      env,
      stdio: "inherit",
    });
    return await new Promise((resolve, reject) => {
      child.on("error", reject);
      child.on("exit", (code) => resolve(code || 0));
    });
  }

  // Electron logs to a file here, and its "shown" line tells the launcher the
  // window is open, so the console can close.
  const log = path.join(
    os.tmpdir(),
    `dazedtl-${crypto.createHash("sha256").update(root).digest("hex").slice(0, 12)}.log`,
  );
  const output = fs.openSync(log, "w");
  const child = spawn(electron, [app, ...forward], {
    cwd: root,
    env: { ...env, DAZEDTL_LAUNCH_SIGNAL: "1" },
    detached: true,
    stdio: ["ignore", output, output],
  });
  fs.closeSync(output);
  let exit = null;
  child.on("exit", (code) => (exit = code ?? 1));
  child.on("error", () => (exit = 1));
  console.log("Opening DazedTL…");
  for (let waited = 0; waited < 120_000; waited += 150) {
    if (exit !== null) break;
    if (fs.readFileSync(log, "utf8").includes("dazedtl:shown")) break;
    await delay(150);
  }
  if (exit !== null && exit !== 0) {
    const tail = fs
      .readFileSync(log, "utf8")
      .trim()
      .split("\n")
      .slice(-15)
      .join("\n");
    throw new Error(
      `The app closed while starting.${tail ? `\n\n${tail}` : ""}`,
    );
  }
  child.unref();
  return 0;
}

try {
  process.exitCode = await launch();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`\nDazedTL could not start.\n${message}`);
  alert(message);
  process.exitCode = 1;
}
