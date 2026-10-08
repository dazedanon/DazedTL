import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { root, requireNode } from "./dependencies.mjs";

// One deadline covers discovery, both runtimes, fixtures, and teardown. CI's
// slower runners set their own in DAZEDTL_TEST_BUDGET, in seconds.
const budget = Number(process.env.DAZEDTL_TEST_BUDGET || 10) * 1000;
const elapsed = () => process.uptime() * 1000;
requireNode();
const python = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const tests = fs.globSync("tests/**/*.test.ts", { cwd: root }).sort();
if (!tests.length) throw new Error("No frontend behavior tests were found.");
const commands = [
  [
    python,
    [
      "-I",
      "-X",
      "utf8",
      "-B",
      "-m",
      "unittest",
      "discover",
      "-s",
      "tests",
      "-t",
      ".",
      "-p",
      "test_*.py",
      "--durations",
      "5",
    ],
  ],
  [process.execPath, ["--test", "--test-isolation=none", ...tests]],
];
let failed = false;
for (const [command, args] of commands) {
  const remaining = Math.floor(budget - elapsed());
  if (remaining <= 0) {
    failed = true;
    break;
  }
  const result = spawnSync(command, args, {
    cwd: root,
    env: { ...process.env, NODE_OPTIONS: "" },
    stdio: "inherit",
    timeout: remaining,
    killSignal: "SIGKILL",
    windowsHide: true,
  });
  if (result.error) console.error(result.error.message);
  failed ||= result.status !== 0;
  if (elapsed() >= budget) break;
}
const seconds = elapsed() / 1000;
console.log(
  "Full test suite: " + seconds.toFixed(3) + "s / " + budget / 1000 + "s",
);
if (elapsed() >= budget) {
  console.error(
    "Test runtime budget exceeded. Do not expand coverage until the overrun is resolved.",
  );
  failed = true;
}
process.exitCode = failed ? 1 : 0;
