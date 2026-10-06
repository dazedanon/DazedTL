import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { app, root, dependencies } from "./dependencies.mjs";
// Rebuild when renderer inputs changed since the last build, such as after
// updating the checkout; the backend refuses a renderer built from older contracts.
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
if (
  built === undefined ||
  inputs.some((file) => fs.statSync(path.join(root, file)).mtimeMs > built)
)
  await import("./build.mjs");
const require = createRequire(
  path.join(dependencies(), "electron/package.json"),
);
const electron = require("electron");
const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(electron, [app, ...process.argv.slice(2)], {
  cwd: root,
  env,
  stdio: "inherit",
});
child.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on("exit", (code) => process.exit(code || 0));
