// The release check: everything CI runs, on this machine, in about three
// minutes on Linux. The build checks first, then the behavior tests, then the
// previous-release QA check, every CI scenario, the live test and the upgrade
// test side by side, each in a private display of its own. Prints one table of
// what passed and failed, with each one's log. See "Live test" in
// docs/development.md.
//
//   node scripts/release-check.mjs [--jobs <n>] [--work <folder>]
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { root, requireNode } from "./dependencies.mjs";
import { ensureRenderer } from "./testkit/app.mjs";
import { checkout, previousRelease } from "./testkit/checkout.mjs";
import { withRetry } from "./testkit/retry.mjs";
import { ciScenarios } from "./testkit/ci.mjs";

requireNode();
const option = (name) => {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
};
const work = path.resolve(
  option("--work") ||
    fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-release-check-")),
);
fs.mkdirSync(work, { recursive: true });
if (fs.readdirSync(work).length)
  throw new Error(`Choose an empty work folder; ${work} has files.`);
// Each app runs its backend and a display beside it.
const jobs = Number(
  option("--jobs") ||
    Math.max(2, Math.min(10, Math.floor(os.availableParallelism() / 2))),
);

const results = [];
/** A file or folder name for the check `name`. */
const slug = (name) => name.replace(/[^\w.-]+/g, "_");
const folder = (name) => path.join(work, slug(name));

/** Runs `args` with Node once, its output in `log`; resolves whether it passed. */
function attempt(args, log) {
  const output = fs.openSync(log, "w");
  return new Promise((resolve) => {
    const child = spawn(process.execPath, args, {
      cwd: root,
      stdio: ["ignore", output, output],
    });
    const finish = (passed) => {
      fs.closeSync(output);
      resolve(passed);
    };
    child.on("error", () => finish(false));
    child.on("close", (code) => finish(code === 0));
  });
}

/**
 * Copies the logs folders a failed first attempt left in `kept`, its own and
 * an upgrade's previous release's, to `<work>/<name>.first`, so a flake's
 * app logs stay readable after its files are cleared.
 */
function keepLogs(name, kept) {
  for (const folder of ["logs", "previous/logs"]) {
    const logs = path.join(kept, folder);
    if (fs.existsSync(logs))
      fs.cpSync(logs, path.join(work, `${slug(name)}.first`, folder), {
        recursive: true,
      });
  }
}

/**
 * Runs `args` with Node, its output in `<work>/<name>.log` and its files in
 * `kept`. A failed run gets one more, its output in `<name>.retry.log` and
 * its files cleared first but its logs folders kept in `<name>.first`; one
 * that passes then is a flake.
 */
async function run(name, args, kept = "") {
  const first = path.join(work, `${slug(name)}.log`);
  const result = {
    name,
    passed: false,
    flaky: false,
    seconds: 0,
    log: first,
    first,
    kept,
  };
  results.push(result);
  const started = Date.now();
  const outcome = await withRetry(
    async (number) => {
      if (number === 2) {
        console.log(`failed  ${name}; running it once more`);
        result.log = path.join(work, `${slug(name)}.retry.log`);
      }
      return attempt(args, result.log);
    },
    () => {
      if (!kept) return;
      try {
        keepLogs(name, kept);
      } catch (error) {
        console.log(
          `Could not keep ${name}'s first logs: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
      fs.rmSync(kept, { recursive: true, force: true });
    },
  );
  Object.assign(result, outcome, { seconds: (Date.now() - started) / 1000 });
  // A check that passed leaves only its log, since the live tests' installs
  // take gigabytes; its app has exited, so nothing writes there any more.
  if (outcome.passed && kept) fs.rmSync(kept, { recursive: true, force: true });
  console.log(
    `${outcome.flaky ? "flaky " : outcome.passed ? "passed" : "FAILED"}  ${name} (${result.seconds.toFixed(0)} s)`,
  );
  return result;
}

/** Runs the tasks `jobs` at a time, in order. */
async function pool(tasks) {
  const queue = [...tasks];
  await Promise.all(
    Array.from({ length: jobs }, async () => {
      while (queue.length) await queue.shift()();
    }),
  );
}

const started = Date.now();
const script = (name) => path.join(root, "scripts", name);
const runs = ciScenarios();
console.log(`Release check in ${work}, ${jobs} at a time.`);
// The behavior tests have a time budget, so they run before the rest.
await run("build", [script("build.mjs")]);
await run("test", [script("test.mjs")]);
// Scenarios share this checkout's interface and the previous release's
// checkout, so both are ready before they start side by side.
await ensureRenderer(root);
await checkout(previousRelease());
const scenario =
  (args, name = args.join(" ")) =>
  () =>
    run(
      name,
      [script("scenario.mjs"), ...args, "--work", folder(name)],
      folder(name),
    );
// The two longest first, so the scenarios fill in beside them.
await pool([
  scenario(["live"], "live test"),
  scenario(["live", "--upgrade-from", "previous"], "upgrade test"),
  ...runs.map((args) => scenario(args)),
  () =>
    run(
      "previous-release QA check",
      [script("qa-upgrade.mjs"), "--work", folder("qa-upgrade")],
      folder("qa-upgrade"),
    ),
]);

const width = Math.max(...results.map((result) => result.name.length));
console.log(`\n${"Check".padEnd(width)}  Result  Time   Log`);
for (const result of results)
  console.log(
    `${result.name.padEnd(width)}  ${result.flaky ? "flaky " : result.passed ? "passed" : "FAILED"}  ${`${result.seconds.toFixed(0)} s`.padEnd(5)}  ${result.log}`,
  );
const failed = results.filter((result) => !result.passed);
const flaky = results.filter((result) => result.flaky);
console.log(
  `\n${failed.length ? `${failed.length} of ${results.length} failed; their folders stay beside the logs` : `All ${results.length} passed`}${flaky.length ? ` (flaky, passed on retry: ${flaky.map((result) => `${result.name}, first log ${result.first}, its logs folders in ${path.join(work, `${slug(result.name)}.first`)}`).join("; ")})` : ""} in ${((Date.now() - started) / 1000).toFixed(0)} s.`,
);
process.exitCode = failed.length ? 1 : 0;
