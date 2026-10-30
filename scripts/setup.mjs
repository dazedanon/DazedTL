// Installs what DazedTL runs on into this folder: the pinned Python, the locked
// Python and Node packages, and Electron. A step reruns only when its inputs
// change, so launching after an update or a moved folder repairs the install.
// Run directly for development tools; the launcher installs the user set.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import {
  app,
  root,
  runtime,
  python,
  platform,
  platforms,
  requireNode,
  bundledGit,
} from "./dependencies.mjs";
import { replaceFolder, settle } from "./files.mjs";
import { extract } from "./tar.mjs";
import { extract as unzip } from "./zip.mjs";

const stateName = ".runtime/state.json";

/** @returns {{ system?: string, mode?: "user" | "dev", venv?: "managed", pip?: string, npm?: string }} */
export function readState(folder = root) {
  try {
    return JSON.parse(fs.readFileSync(path.join(folder, stateName), "utf8"));
  } catch {
    return {};
  }
}

export function writeState(state, folder = root) {
  const file = path.join(folder, stateName);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(`${file}.partial`, JSON.stringify(state, null, 2));
  settle(() => fs.renameSync(`${file}.partial`, file));
}

function digest(...parts) {
  const hash = crypto.createHash("sha256");
  for (const part of parts) hash.update(part).update("\0");
  return hash.digest("hex");
}

const read = (file) => fs.readFileSync(path.join(root, file));

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    windowsHide: true,
    ...options,
  });
  if (result.error || result.status !== 0)
    throw new Error(
      `${path.basename(command)} could not finish. Check the output above.`,
    );
}

/** Finds the pinned download whose file name passes `test`. */
export function pinned(test) {
  for (const line of fs
    .readFileSync(path.join(root, "scripts/runtimes.lock"), "utf8")
    .split("\n")) {
    const [hash, url] = line.trim().split(/\s+/);
    if (
      url &&
      !line.startsWith("#") &&
      test(url.slice(url.lastIndexOf("/") + 1))
    )
      return { hash, url };
  }
  throw new Error(`DazedTL has no pinned runtime for ${platform}.`);
}

/** A dropped connection or a busy server, which another try can get past. */
function transient(error) {
  const status = error?.status ?? error?.response?.status;
  if (status) return status === 408 || status === 429 || status >= 500;
  // fetch reports a failed or cut connection as a TypeError with its cause.
  return error instanceof TypeError && error.cause !== undefined;
}

/**
 * Runs a download up to three times, since a first start on a flaky network
 * can lose a connection; a missing file or a wrong checksum fails at once.
 */
export async function retried(label, attempt, pause = 2000) {
  for (let tries = 1; ; tries++) {
    try {
      return await attempt();
    } catch (error) {
      if (!transient(error)) throw error;
      const reason =
        error.cause?.code ||
        error.status ||
        error.response?.status ||
        error.message;
      if (tries === 3)
        throw new Error(
          `${label} could not be downloaded (${reason}). Check the internet connection, then start DazedTL again.`,
          { cause: error },
        );
      console.log(`The ${label} download failed (${reason}). Trying again…`);
      await delay(tries * pause);
    }
  }
}

/** Downloads a pinned file into memory and checks its published checksum. */
export function download(pin, label) {
  return retried(label, () => downloadOnce(pin, label));
}

async function downloadOnce({ hash, url }, label) {
  const response = await fetch(url, {
    headers: { "User-Agent": "DazedTL" },
    signal: AbortSignal.timeout(15 * 60_000),
  });
  if (!response.ok || !response.body)
    throw Object.assign(
      new Error(`${label} could not be downloaded (${response.status}).`),
      { status: response.status },
    );
  const total = Number(response.headers.get("content-length")) || 0;
  const chunks = [];
  let received = 0;
  let shown = -1;
  for await (const chunk of response.body) {
    chunks.push(chunk);
    received += chunk.length;
    const percent = total ? Math.floor((received / total) * 10) * 10 : -1;
    if (percent > shown) {
      shown = percent;
      console.log(`Downloading ${label}… ${percent}%`);
    }
  }
  const data = Buffer.concat(chunks);
  if (crypto.createHash("sha256").update(data).digest("hex") !== hash)
    throw new Error(`${label} did not match its pinned checksum. Try again.`);
  return data;
}

/** Unpacks a runtime beside `folder`, so an interrupted start leaves none half-installed. */
function install(folder, unpack) {
  const staging = `${folder}.partial`;
  settle(() => fs.rmSync(staging, { recursive: true, force: true }));
  unpack(staging);
  replaceFolder(staging, folder);
}

function managedExecutable(version) {
  return path.join(
    runtime,
    `python-${version}`,
    process.platform === "win32" ? "python.exe" : "bin/python3",
  );
}

async function managedPython(version) {
  const target = platforms[platform];
  if (!target) throw new Error(`DazedTL does not support ${platform}.`);
  const folder = path.join(runtime, `python-${version}`);
  const executable = managedExecutable(version);
  if (fs.existsSync(executable)) return executable;
  const archive = await download(
    pinned(
      (name) =>
        name.startsWith(`cpython-${version}+`) &&
        name.includes(`-${target.python}-install_only`),
    ),
    `Python ${version}`,
  );
  install(folder, (staging) => extract(archive, staging, { strip: 1 }));
  return executable;
}

function version(interpreter) {
  const result = spawnSync(
    interpreter,
    ["-I", "-c", "import platform; print(platform.python_version())"],
    { encoding: "utf8", windowsHide: true },
  );
  return result.status === 0 ? result.stdout.trim() : "";
}

/** Whether .venv was created from the Python in `folder`, per pyvenv.cfg. */
function createdFrom(folder) {
  try {
    const config = fs.readFileSync(path.join(root, ".venv/pyvenv.cfg"), "utf8");
    const home = /^home\s*=\s*(.+)$/m.exec(config)?.[1].trim() || "";
    const same = (value) => {
      const resolved = fs.realpathSync(value);
      return process.platform === "win32" ? resolved.toLowerCase() : resolved;
    };
    return same(home) === same(folder);
  } catch {
    return false;
  }
}

function removeOld(pattern, keep) {
  for (const name of fs.readdirSync(runtime))
    if (pattern.test(name) && name !== keep)
      try {
        fs.rmSync(path.join(runtime, name), { recursive: true, force: true });
      } catch {
        // A runtime still in use is removed by a later setup.
      }
}

/** How a system's Node build is named in its folder. */
const nodeBuild = (system) =>
  platforms[system].node.replace(/\.(zip|tar\.gz)$/, "");

/** The folder name of the pinned Node for this system. */
function nodeFolder() {
  if (!platforms[platform])
    throw new Error(`DazedTL does not support ${platform}.`);
  const version = read(".node-version").toString().trim();
  return `node-v${version}-${nodeBuild(platform)}`;
}

function runtimeNames(folder) {
  const runtimes = path.join(folder, ".runtime");
  return fs.existsSync(runtimes) ? fs.readdirSync(runtimes) : [];
}

/**
 * What runs only on the system that installed it yet has the same path on
 * every system. Node and MinGit stay out: each system's has a name of its own.
 */
function systemFiles(folder) {
  return [
    ".venv",
    "app/node_modules",
    ...runtimeNames(folder)
      .filter((name) => name.startsWith("python-"))
      .map((name) => `.runtime/${name}`),
  ];
}

/** The system whose install is in `folder`. */
function installedSystem(folder, system) {
  const recorded = readState(folder).system;
  if (recorded) return recorded;
  // Installs from before the record: a finished setup removed every other
  // system's Node, so another system's Node here means that system's install.
  const names = runtimeNames(folder);
  return (
    Object.keys(platforms).find(
      (other) =>
        other !== system &&
        names.some(
          (name) =>
            name.startsWith("node-v") && name.endsWith(`-${nodeBuild(other)}`),
        ),
    ) ?? system
  );
}

/**
 * A folder on a drive that two systems share, such as a dual-boot partition,
 * holds one system's install at a time: the other's waits in .runtime/parked,
 * so only the first start on each system installs anything. Moving it never
 * reads inside it, which matters for links that only its own system can follow.
 * The state file names the install in place, so it moves last and comes back
 * first, and a stopped switch picks up where it left off.
 */
export function switchSystem(folder = root, system = platform) {
  const installed = installedSystem(folder, system);
  if (installed !== system) {
    console.log(
      "This folder last ran on another system. Switching it to this one…",
    );
    const parked = path.join(folder, ".runtime", "parked");
    const move = (name, from, to) => {
      const source = path.join(from, name);
      if (!fs.existsSync(source)) return;
      const target = path.join(to, name);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      replaceFolder(source, target);
    };
    const away = path.join(parked, installed);
    const back = path.join(parked, system);
    for (const name of [...systemFiles(folder), stateName])
      move(name, folder, away);
    for (const name of [stateName, ...systemFiles(back)])
      move(name, back, folder);
  }
  const state = readState(folder);
  if (state.system !== system) writeState({ ...state, system }, folder);
}

/**
 * The pinned Node and its npm, so every install resolves packages the same
 * way; the system Node may have no npm or a different version. START provides
 * it on Windows; elsewhere setup can fetch it itself.
 */
async function npm() {
  const name = nodeFolder();
  const folder = path.join(runtime, name);
  const windows = process.platform === "win32";
  let node = path.join(folder, windows ? "node.exe" : "bin/node");
  if (!fs.existsSync(node)) {
    if (windows) node = process.execPath;
    else {
      const archive = await download(
        pinned((file) => file === `${name}.tar.gz`),
        name,
      );
      install(folder, (staging) => extract(archive, staging, { strip: 1 }));
    }
  }
  const directory = path.dirname(node);
  for (const cli of [
    path.join(directory, "node_modules/npm/bin/npm-cli.js"),
    path.join(directory, "../lib/node_modules/npm/bin/npm-cli.js"),
  ])
    if (fs.existsSync(cli)) return { node, cli };
  throw new Error("Start DazedTL with START, which installs its own Node.");
}

/**
 * Installs exactly the packages an app folder's lock names, without their
 * install scripts; Electron's binary comes from `installElectron`.
 * @param {string} app the app folder
 * @param {"user" | "dev"} mode users skip the development tools
 */
export async function installPackages(app, mode) {
  const { node, cli } = await npm();
  run(
    node,
    [
      cli,
      "ci",
      "--ignore-scripts",
      "--no-audit",
      "--no-fund",
      "--no-update-notifier",
      ...(mode === "user" ? ["--omit=dev"] : []),
    ],
    { cwd: app },
  );
}

/**
 * Installs Electron's binary into its package the way its install.js does,
 * except that the archive is unpacked here: install.js unpacks with a native
 * module that needs the Visual C++ runtime, which a fresh Windows lacks.
 * @param {string} electron the node_modules/electron folder
 */
export async function installElectron(electron) {
  const require = createRequire(path.join(electron, "install.js"));
  const executable = {
    darwin: "Electron.app/Contents/MacOS/Electron",
    linux: "electron",
    win32: "electron.exe",
  }[process.platform];
  if (!executable)
    throw new Error(`Electron has no build for ${process.platform}.`);
  const { downloadArtifact } = require("@electron/get");
  const archive = await retried("Electron", () =>
    downloadArtifact({
      version: require("./package.json").version,
      artifactName: "electron",
      platform: process.platform,
      arch: process.arch,
      checksums: require("./checksums.json"),
    }),
  );
  const dist = path.join(electron, "dist");
  settle(() => fs.rmSync(dist, { recursive: true, force: true }));
  unzip(fs.readFileSync(archive), dist);
  // install.js keeps the type definitions beside the package's own.
  const types = path.join(dist, "electron.d.ts");
  if (fs.existsSync(types))
    settle(() => fs.renameSync(types, path.join(electron, "electron.d.ts")));
  fs.writeFileSync(path.join(electron, "path.txt"), executable);
}

/**
 * Brings the install up to date. Users get the packages DazedTL runs with;
 * development adds the formatters, linters and type checkers.
 * @param {{ mode: "user" | "dev" }} options
 */
export async function ensureSetup({ mode }) {
  requireNode();
  fs.mkdirSync(runtime, { recursive: true });
  switchSystem();
  const state = readState();
  const pythonVersion = read(".python-version").toString().trim();

  const environment = path.join(root, ".venv");
  if (fs.lstatSync(environment, { throwIfNoEntry: false })?.isSymbolicLink())
    throw new Error(
      "The .venv folder is a link. Move the link aside before creating a local environment.",
    );
  const expected =
    process.env.DAZEDTL_PYTHON || managedExecutable(pythonVersion);
  let created = false;
  // A managed environment is current while it points at the pinned Python's
  // folder, which a moved install or a new Python version changes.
  const current =
    state.venv === "managed"
      ? createdFrom(path.dirname(expected))
      : // A development environment from before managed setup stays in place
        // while it runs the pinned Python.
        fs.existsSync(environment) && version(python) === pythonVersion;
  if (!current) {
    const base =
      process.env.DAZEDTL_PYTHON || (await managedPython(pythonVersion));
    console.log(`Creating the Python environment (${pythonVersion})…`);
    settle(() => fs.rmSync(environment, { recursive: true, force: true }));
    run(base, ["-I", "-m", "venv", environment]);
    if (version(python) !== pythonVersion)
      throw new Error(`The new .venv does not run Python ${pythonVersion}.`);
    state.venv = "managed";
    created = true;
  }

  const locks = [
    "backend/requirements.lock",
    ...(mode === "dev" ? ["backend/requirements-dev.lock"] : []),
  ];
  const pipKey = digest(mode, pythonVersion, ...locks.map(read));
  if (created || state.pip !== pipKey) {
    console.log("Installing Python packages…");
    run(python, [
      "-I",
      "-m",
      "pip",
      "install",
      "--disable-pip-version-check",
      "--require-hashes",
      ...locks.flatMap((lock) => ["-r", path.join(root, lock)]),
    ]);
    state.pip = pipKey;
    writeState(state);
  }

  // Unlink the former development shortcut without touching its sibling target.
  const modules = path.join(app, "node_modules");
  if (fs.lstatSync(modules, { throwIfNoEntry: false })?.isSymbolicLink())
    fs.unlinkSync(modules);
  // Every release bumps the app's own version in the lock; only the
  // dependencies decide whether packages need installing again.
  const lock = JSON.parse(read("app/package-lock.json").toString());
  delete lock.version;
  delete lock.packages?.[""]?.version;
  const npmKey = digest(mode, JSON.stringify(lock));
  const electron = path.join(modules, "electron");
  if (
    state.npm !== npmKey ||
    !fs.existsSync(path.join(modules, ".package-lock.json"))
  ) {
    console.log("Installing application packages…");
    await installPackages(app, mode);
    state.npm = npmKey;
  }
  if (!fs.existsSync(path.join(electron, "path.txt"))) {
    console.log("Installing Electron…");
    await installElectron(electron);
  }
  // Translation projects are Git repositories, and Windows ships no Git.
  // MinGit's system config sets core.autocrlf=true as Git for Windows does,
  // which the engine's repo-local line-ending settings already override.
  const git = bundledGit();
  if (git) {
    if (!fs.existsSync(path.join(git.bin, "git.exe"))) {
      const archive = await download(
        pinned((file) => /^MinGit-[\d.]+-64-bit\.zip$/.test(file)),
        "Git",
      );
      install(git.folder, (staging) => unzip(archive, staging));
    }
    removeOld(/^mingit-/, path.basename(git.folder));
  } else if (spawnSync("git", ["--version"], { stdio: "ignore" }).status !== 0)
    throw new Error(
      process.platform === "darwin"
        ? "DazedTL needs Git. Run xcode-select --install in Terminal, then start DazedTL again."
        : "DazedTL needs Git. Install the git package with your system's package manager, then start DazedTL again.",
    );
  state.mode = mode;
  writeState(state);
  if (state.venv === "managed" && !process.env.DAZEDTL_PYTHON)
    removeOld(/^python-/, `python-${pythonVersion}`);
  // Another system's Node stays for that system's next start in this folder.
  removeOld(new RegExp(`^node-v.*-${nodeBuild(platform)}`), nodeFolder());
}

if (import.meta.main) {
  await ensureSetup({ mode: process.argv.includes("--user") ? "user" : "dev" });
  console.log(
    "Dependencies installed. Run node scripts/build.mjs, then node scripts/start.mjs.",
  );
}
