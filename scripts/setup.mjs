import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { app, root, requireNode } from "./dependencies.mjs";

requireNode();
const manifest = JSON.parse(
  fs.readFileSync(path.join(app, "package.json"), "utf8"),
);
const npmVersion = manifest.packageManager.split("@")[1];
const pythonVersion = fs
  .readFileSync(path.join(root, ".python-version"), "utf8")
  .trim();
const python =
  process.env.DAZEDTL_PYTHON ||
  (process.platform === "win32" ? "python" : "python3");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";

function run(command, args, { cwd = root, capture = false } = {}) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: capture ? "pipe" : "inherit",
    encoding: "utf8",
    shell: command === "npm.cmd",
  });
  if (result.error || result.status !== 0)
    throw new Error(
      `${command} could not finish. Check the installed runtime and the output above.`,
    );
  return capture ? result.stdout.trim() : "";
}

if (run(npm, ["--version"], { capture: true }) !== npmVersion)
  throw new Error(`Use npm ${npmVersion}, as pinned in app/package.json.`);
if (
  run(
    python,
    ["-I", "-c", "import platform; print(platform.python_version())"],
    { capture: true },
  ) !== pythonVersion
)
  throw new Error(`Use Python ${pythonVersion}, as pinned in .python-version.`);

const environment = path.join(root, ".venv");
const interpreter = path.join(
  environment,
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
if (fs.lstatSync(environment, { throwIfNoEntry: false })?.isSymbolicLink())
  throw new Error(
    "The .venv folder is a link. Move the link aside before creating a local environment.",
  );

// Unlink the former development shortcut without touching its sibling target.
const modules = path.join(app, "node_modules");
if (fs.lstatSync(modules, { throwIfNoEntry: false })?.isSymbolicLink())
  fs.unlinkSync(modules);
run(npm, ["ci", "--ignore-scripts", "--no-audit", "--no-fund"], { cwd: app });
run(process.execPath, [path.join(modules, "electron/install.js")]);

if (!fs.existsSync(interpreter)) run(python, ["-m", "venv", environment]);
if (
  run(
    interpreter,
    ["-I", "-c", "import platform; print(platform.python_version())"],
    { capture: true },
  ) !== pythonVersion
)
  throw new Error(
    `The existing .venv uses a different Python. Recreate it with Python ${pythonVersion}.`,
  );
run(interpreter, [
  "-I",
  "-m",
  "pip",
  "install",
  "--require-hashes",
  "-r",
  path.join(root, "backend/requirements.lock"),
]);
console.log(
  "Locked dependencies installed. Run node scripts/build.mjs, then node scripts/start.mjs.",
);
