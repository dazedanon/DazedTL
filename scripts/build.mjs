import path from "node:path";
import { spawnSync } from "node:child_process";
import { app, dependencies } from "./dependencies.mjs";
const modules = dependencies();
for (const args of [
  [path.join(modules, "typescript/bin/tsc"), "--noEmit"],
  [path.join(modules, "vite/bin/vite.js"), "build"],
]) {
  const result = spawnSync(process.execPath, args, {
    cwd: app,
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status || 1);
}
