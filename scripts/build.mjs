import path from "node:path";
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
];
const build = [
  node("typescript/bin/tsc", ["--noEmit"], { cwd: app }),
  node("vite/bin/vite.js", ["build"], { cwd: app }),
];
// Launching builds a missing renderer without requiring clean static checks.
for (const step of [...(import.meta.main ? checks : []), ...build]) {
  const result = spawnSync(step.command, step.args, {
    cwd: step.cwd || root,
    env: { ...process.env, ...step.env },
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status || 1);
}
