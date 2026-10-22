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
import { scenarios } from "./testkit/scenarios.mjs";

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

/**
 * The scenario runs CI's matrix lists, each a name and the options after it,
 * so this check and CI run the same set.
 */
function ciScenarios() {
  const text = fs.readFileSync(
    path.join(root, ".github/workflows/ci.yml"),
    "utf8",
  );
  const block = /\n(\s+)scenarios:\n((?:\1\s+- .+\n)+)/.exec(text);
  if (!block) throw new Error("CI's workflow lists no scenarios.");
  const runs = [];
  for (const line of block[2].trim().split("\n")) {
    let previous = "";
    for (const word of line
      .replace(/^\s*- /, "")
      .trim()
      .split(/\s+/)) {
      if (word.startsWith("--") || previous.startsWith("--"))
        runs[runs.length - 1].push(word);
      else runs.push([word]);
      previous = word;
    }
  }
  const missing = Object.keys(scenarios).filter(
    (name) => !runs.some(([run]) => run === name),
  );
  if (missing.length)
    throw new Error(`CI runs no ${missing.join(", ")} scenario; add it there.`);
  return runs;
}

const results = [];
/** A file or folder name for the check `name`. */
const slug = (name) => name.replace(/[^\w.-]+/g, "_");
// A scenario's display is named after its folder, which this check's own
// folder name keeps apart from other sessions' scenarios.
const folder = (name) =>
  path.join(work, `${slug(name)}-${path.basename(work).slice(-6)}`);

/** Runs `args` with Node, its output in `<work>/<name>.log` and its files in
 * `kept`. */
function run(name, args, kept = "") {
  const log = path.join(work, `${slug(name)}.log`);
  const output = fs.openSync(log, "w");
  const result = { name, passed: false, seconds: 0, log, kept };
  results.push(result);
  const started = Date.now();
  return new Promise((resolve) => {
    const child = spawn(process.execPath, args, {
      cwd: root,
      stdio: ["ignore", output, output],
    });
    const finish = (passed) => {
      fs.closeSync(output);
      Object.assign(result, { passed, seconds: (Date.now() - started) / 1000 });
      console.log(
        `${passed ? "passed" : "FAILED"}  ${name} (${result.seconds.toFixed(0)} s)`,
      );
      resolve(result);
    };
    child.on("error", () => finish(false));
    child.on("close", (code) => finish(code === 0));
  });
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
checkout(previousRelease());
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

// A check that passed leaves only its log, since the live tests' installs
// take gigabytes; once all have ended, as an app's last writes have too.
for (const result of results)
  if (result.passed && result.kept)
    fs.rmSync(result.kept, { recursive: true, force: true });

const width = Math.max(...results.map((result) => result.name.length));
console.log(`\n${"Check".padEnd(width)}  Result  Time   Log`);
for (const result of results)
  console.log(
    `${result.name.padEnd(width)}  ${result.passed ? "passed" : "FAILED"}  ${`${result.seconds.toFixed(0)} s`.padEnd(5)}  ${result.log}`,
  );
const failed = results.filter((result) => !result.passed);
console.log(
  `\n${failed.length ? `${failed.length} of ${results.length} failed; their folders stay beside the logs` : `All ${results.length} passed`} in ${((Date.now() - started) / 1000).toFixed(0)} s.`,
);
process.exitCode = failed.length ? 1 : 0;
