import path from "node:path";
import { spawnSync } from "node:child_process";
import { app, root, dependencies } from "./dependencies.mjs";
const modules = dependencies();
const steps = [
  [path.join(modules, "typescript/bin/tsc"), "--noEmit"],
  [path.join(modules, "vite/bin/vite.js"), "build"],
];
// Launching builds a missing renderer without requiring formatted sources.
if (import.meta.main)
  steps.unshift([path.join(root, "scripts/format.mjs"), "--check"]);
for (const args of steps) {
  const result = spawnSync(process.execPath, args, {
    cwd: app,
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status || 1);
}
