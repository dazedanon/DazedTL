import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import { app, root, dependencies } from "./dependencies.mjs";
const modules = dependencies();
const ruff = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/ruff.exe" : "bin/ruff",
);
const tsgolint = path.join(
  modules,
  `@oxlint-tsgolint/${process.platform}-${process.arch}`,
  process.platform === "win32" ? "tsgolint.exe" : "tsgolint",
);
const node = (script, args, options = {}) => ({
  command: process.execPath,
  args: [path.join(modules, script), ...args],
  ...options,
});
const checks = [
  { command: process.execPath, args: ["scripts/format.mjs", "--check"] },
  { command: process.execPath, args: ["scripts/contracts.mjs", "--check"] },
  { command: process.execPath, args: ["scripts/styles.mjs"] },
  { command: process.execPath, args: ["scripts/paths.mjs"] },
  node(
    "oxlint/bin/oxlint",
    [
      "--type-aware",
      "app/src",
      "app/electron",
      "app/vite.config.ts",
      "scripts",
    ],
    { env: { OXLINT_TSGOLINT_PATH: tsgolint } },
  ),
  { command: ruff, args: ["check", "--quiet", "."] },
  node("pyright/index.js", []),
  node("typescript/bin/tsc", ["-p", "app/electron"]),
  node("typescript/bin/tsc", ["--noEmit"], { cwd: app }),
];
function run(steps) {
  for (const step of steps) {
    const result = spawnSync(step.command, step.args, {
      cwd: step.cwd || root,
      env: { ...process.env, ...step.env },
      stdio: "inherit",
    });
    if (result.status !== 0)
      throw new Error("The build could not finish. Check the output above.");
  }
}
// What the renderer build reads. Its digest, not file times, decides whether a
// build is current: a ZIP unpacked over an install keeps the archive's older
// timestamps, and clocks can move backwards.
const rendererInputs = [
  "app/src/**",
  "app/index.html",
  "app/package-lock.json",
  "app/tsconfig.json",
  "app/vite.config.ts",
  "backend/dazedtl/api/protocol.json",
];
const stamp = path.join(app, "dist/.inputs");
function rendererDigest() {
  const hash = crypto.createHash("sha256");
  const files = fs
    .globSync(rendererInputs, { cwd: root })
    .filter((file) => fs.statSync(path.join(root, file)).isFile())
    .map((file) => file.replaceAll("\\", "/"))
    .sort();
  for (const file of files)
    hash
      .update(file)
      .update("\0")
      .update(fs.readFileSync(path.join(root, file)))
      .update("\0");
  return hash.digest("hex");
}
/** Whether the built renderer was made from other inputs than the current ones. */
export function rendererStale() {
  try {
    return fs.readFileSync(stamp, "utf8") !== rendererDigest();
  } catch {
    return true;
  }
}
/** Builds the renderer; launching uses this without the development checks. */
export function buildRenderer() {
  const digest = rendererDigest();
  run([node("vite/bin/vite.js", ["build"], { cwd: app })]);
  fs.writeFileSync(stamp, digest);
}
if (import.meta.main) {
  try {
    run(checks);
    buildRenderer();
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
