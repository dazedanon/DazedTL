import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { root, dependencies } from "./dependencies.mjs";

// Formats the checkout in place; --check reports unformatted files instead.
const check = process.argv.includes("--check");
const prettier = path.join(dependencies(), "prettier/bin/prettier.cjs");
const ruff = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/ruff.exe" : "bin/ruff",
);
if (!fs.existsSync(prettier) || !fs.existsSync(ruff))
  throw new Error(
    "Run node scripts/setup.mjs to install the locked formatting tools.",
  );
let failed = false;
for (const [command, args] of [
  [
    process.execPath,
    [prettier, check ? "--check" : "--write", "--log-level", "warn", "."],
  ],
  [
    ruff,
    [
      "format",
      ...(check ? ["--check", "--output-format", "concise"] : []),
      ".",
    ],
  ],
]) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit" });
  if (result.error) console.error(result.error.message);
  failed ||= result.status !== 0;
}
if (failed && check)
  console.error("Run node scripts/format.mjs to format these files.");
process.exitCode = failed ? 1 : 0;
