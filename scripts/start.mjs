import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { app, root, legacy, dependencies } from "./dependencies.mjs";
if (!fs.existsSync(path.join(app, "dist/index.html")))
  await import("./build.mjs");
const require = createRequire(
  path.join(dependencies(), "electron/package.json"),
);
const electron = require("electron");
const env = { ...process.env, DAZEDTL_LEGACY_ROOT: legacy };
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
