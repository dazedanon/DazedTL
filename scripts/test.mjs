import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { root, runtime, requireNode } from "./dependencies.mjs";

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
const deadline = Date.now() + Math.floor(budget - elapsed());
// Compiled modules are kept between runs beside the runtimes, outside version
// control: compiling them again took a second of every run, and each probe's.
const bytecode = path.join(runtime, "test-bytecode");

// Both runtimes run at once; the frontend's report waits for Python's, which
// streams its progress and, near the deadline, where it waits.
function run(command, args, quiet) {
  const child = spawn(command, args, {
    cwd: root,
    env: {
      ...process.env,
      NODE_OPTIONS: "",
      // Python prints where it waits just before this deadline stops it.
      DAZEDTL_TEST_DEADLINE: String(deadline),
    },
    stdio: quiet ? ["ignore", "pipe", "pipe"] : "inherit",
    windowsHide: true,
  });
  const output = [];
  if (quiet) {
    child.stdout.on("data", (chunk) => output.push(chunk));
    child.stderr.on("data", (chunk) => output.push(chunk));
  }
  const timer = setTimeout(
    () => child.kill("SIGKILL"),
    Math.max(0, deadline - Date.now()),
  );
  return new Promise((resolve) => {
    child.on("error", (error) => {
      console.error(error.message);
      resolve({ failed: true, output });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ failed: code !== 0, output });
    });
  });
}

const backend = run(
  python,
  [
    "-I",
    "-X",
    "utf8",
    "-X",
    "pycache_prefix=" + bytecode,
    // Text opened without an encoding fails, as it would on Windows; the
    // filters after it spare libraries DazedTL cannot change.
    "-X",
    "warn_default_encoding",
    "-W",
    "error::EncodingWarning",
    "-W",
    "ignore::EncodingWarning:cv2.load_config_py3",
    "-W",
    "ignore::EncodingWarning:regex._main",
    path.join(root, "tests/run.py"),
    // Each module's time in the last run, so the slowest start first.
    "--times",
    path.join(runtime, "test-times.json"),
  ],
  false,
);
const frontend = run(
  process.execPath,
  ["--test", "--test-isolation=none", ...tests],
  true,
);
const results = [await backend, await frontend];
process.stdout.write(Buffer.concat(results[1].output));
let failed = results.some((result) => result.failed);
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
