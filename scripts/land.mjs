// Lands a finished branch on dev from its worktree, one landing at a time:
// formats it, merges dev in, runs the tests and build, fast-forwards the main
// checkout's dev and pushes it to every mirror. CI then runs on dev, and the
// session that cuts the next release answers for a run still red. Runs on
// Linux and macOS. A wait on the user's DazedTL or a slow landing lock is
// told to the user on the desktop too, since agents run this in the
// background. See "Landing" in docs/development.md.
//
//   node scripts/land.mjs
//
// Exits 0 when landed, 1 when refused or a check failed and 2 on a merge
// conflict.
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import {
  failedJobs,
  failedRun,
  ghToken,
  githubReader,
  workflow,
} from "./ci-wait.mjs";
import { NOTES } from "./changelog.mjs";
import { generated } from "./contracts.mjs";
import { gitIn, withLock } from "./land-lock.mjs";
import { repository } from "./release.mjs";
import { failureReport, tail, testsWithRetry } from "./testkit/retry.mjs";
import { mirrors } from "./update.mjs";

const appPoll = 30_000;
const pushRetry = 60_000;
const pushTimeout = 5 * 60_000;
const icon = path.join(import.meta.dirname, "..", "resources", "icon.png");

/** Whether the user's own DazedTL runs from the main checkout. */
export function appRunning(
  /** @type {string} */ main,
  /** @type {string} */ processes,
) {
  const electron = path.join(main, "app", "node_modules", "electron");
  return processes.split("\n").some((line) => line.includes(electron));
}

/**
 * Waits while the user's DazedTL runs from the main checkout, telling them
 * once when the wait starts and once when it ends. Resolves whether it waited.
 * @param {string} main
 * @param {Pick<Deps, "processes" | "wait">} deps
 * @param {(line: string) => void} tell
 */
export async function waitForApp(main, { processes, wait }, tell) {
  if (!appRunning(main, processes())) return false;
  tell(
    `Your DazedTL is open from ${main}; this lands when it closes (checking every ${appPoll / 1000} s).`,
  );
  do await wait(appPoll);
  while (appRunning(main, processes()));
  tell("Your DazedTL closed; landing now.");
  return true;
}

/**
 * Shows a desktop notification with notify-send on Linux or osascript on
 * macOS, and nothing where the command is missing; never fails the landing.
 */
function notifyDesktop(
  /** @type {string} */ title,
  /** @type {string} */ body,
) {
  const [command, ...args] =
    process.platform === "darwin"
      ? [
          "osascript",
          "-e",
          "on run argv",
          "-e",
          "display notification (item 2 of argv) with title (item 1 of argv)",
          "-e",
          "end run",
          title,
          body,
        ]
      : // The body is markup to notification servers.
        [
          "notify-send",
          "--app-name=DazedTL",
          `--icon=${icon}`,
          title,
          body.replace(
            /[&<>]/g,
            (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[char] ?? "",
          ),
        ];
  spawn(command, args, { stdio: "ignore", timeout: 10_000 }).on(
    "error",
    () => {},
  );
}

/**
 * Where each mirror is pushed: the "all" remote's push URL for it, which
 * holds the SSH address, or else the URL release/mirrors.json names.
 * @param {{ name: string, url: string }[]} list
 * @param {string[]} pushUrls
 */
export function pushTargets(list, pushUrls) {
  return list.map((mirror) => ({
    name: mirror.name,
    url:
      pushUrls.find((url) => repository(url) === repository(mirror.url)) ??
      mirror.url,
  }));
}

/**
 * Times the stages of one landing, to print where the minutes went.
 * @param {() => number} [now]
 */
export function timer(now = Date.now) {
  const started = now();
  let last = started;
  /** @type {[string, number][]} */
  const laps = [];
  const seconds = (/** @type {number} */ ms) => `${Math.round(ms / 1000)} s`;
  return {
    /** Ends the stage that began at the previous lap. */
    lap(/** @type {string} */ name) {
      const at = now();
      laps.push([name, at - last]);
      last = at;
    },
    /** One line: the total from start, then each stage reached. */
    summary() {
      return `Took ${seconds(now() - started)}: ${laps.map(([name, ms]) => `${name} ${seconds(ms)}`).join(", ")}.`;
    },
  };
}

const lines = (/** @type {string} */ text) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
const reason = (/** @type {unknown} */ error) =>
  error instanceof Error ? error.message : String(error);

/**
 * @typedef {{
 *   run: (cwd: string, command: string, args: string[], timeout?: number) => Promise<{ status: number, output: string }>,
 *   processes: () => string,
 *   read: ((route: string) => Promise<any>) | null,
 *   wait: (ms: number) => Promise<unknown>,
 *   log: (line: string) => void,
 *   notify: (title: string, body: string) => void,
 *   onStop: () => void,
 *   now?: () => number,
 * }} Deps
 */

/** Warns, without stopping the landing, when dev's newest CI run failed. */
async function warnRedDev(/** @type {Deps} */ { read, log }, main) {
  const site = mirrors(main).find((mirror) => mirror.type === "github");
  if (!site || !read) return;
  const repo = new URL(site.url).pathname.replace(/^\/|\.git$/g, "");
  try {
    const found = await read(
      `repos/${repo}/actions/workflows/${path.basename(workflow)}/runs?branch=dev&status=completed&per_page=10`,
    );
    const run = (found?.workflow_runs || []).find(
      (/** @type {any} */ item) =>
        !["cancelled", "skipped"].includes(item.conclusion),
    );
    if (!failedRun(run)) return;
    const jobs = await failedJobs(read, repo, run);
    log(
      `CI on dev failed for ${run.head_sha.slice(0, 7)}${jobs.length ? ` (${jobs.join(", ")})` : ""}: ${run.html_url}`,
    );
  } catch (error) {
    log(`Could not read dev's CI: ${reason(error)}`);
  }
}

/**
 * Lands the branch checked out at `cwd`. Resolves the exit code.
 * @param {string} cwd
 * @param {Deps} deps
 */
export async function land(cwd, deps) {
  const { log } = deps;
  if (process.platform === "win32") {
    log("Land from Linux or macOS; land.mjs does not run on Windows.");
    return 1;
  }
  const here = gitIn(cwd);
  const top = here(["rev-parse", "--show-toplevel"]).stdout.trim();
  const git = gitIn(top);
  const out = (/** @type {string[]} */ ...args) => git(args).stdout.trim();
  const branch = out("symbolic-ref", "--quiet", "--short", "HEAD");
  if (!branch || branch === "dev" || branch === "main") {
    log(
      `Land from a feature branch's worktree, not ${branch || "a detached HEAD"}.`,
    );
    return 1;
  }
  const dirty = out("status", "--porcelain");
  if (dirty) {
    log(`Commit or remove these changes first:\n${dirty}`);
    return 1;
  }
  const main = path.dirname(
    path.resolve(top, out("rev-parse", "--git-common-dir")),
  );
  await warnRedDev(deps, main);
  const time = timer(deps.now);
  const unformatted = await formatBranch(git, top, deps.run, log);
  if (unformatted) {
    for (const line of unformatted.report) log(line);
    return unformatted.code;
  }
  time.lap("format");
  // A wait on something outside the landing reaches the user on the desktop,
  // and its line is marked for an agent watching the output.
  const tell = (/** @type {string} */ line) => {
    log(`Notice: ${line}`);
    deps.notify(`Landing ${branch}`, line);
  };
  const { code, report } = await withLock(
    git,
    { branch, worktree: top },
    () => underLock(deps, { top, main, branch }, time, tell),
    { log, notify: tell, onStop: deps.onStop },
  );
  for (const line of report) log(line);
  log(time.summary());
  return code;
}

/**
 * Formats the branch at `top` with format.mjs, which knows what to leave
 * alone, and commits what it changed as `style: format`, so a landing never
 * fails on formatting alone. Resolves null when the branch is formatted,
 * else exit code 1 and the report.
 * @param {ReturnType<typeof gitIn>} git
 * @param {string} top
 * @param {Deps["run"]} run
 * @param {Deps["log"]} log
 * @returns {Promise<{ code: number, report: string[] } | null>}
 */
export async function formatBranch(git, top, run, log) {
  const formatted = await run(top, process.execPath, ["scripts/format.mjs"]);
  if (formatted.status !== 0)
    return {
      code: 1,
      report: [tail(formatted.output), "node scripts/format.mjs failed."],
    };
  const changed = lines(git(["diff", "--name-only"]).stdout);
  if (!changed.length) return null;
  git(["add", "--update"]);
  const commit = git([
    "commit",
    "--quiet",
    "-m",
    "style: format",
    "-m",
    `- Format ${changed.join(", ")} as format.mjs does`,
  ]);
  if (commit.status !== 0)
    return { code: 1, report: [tail(commit.stdout + commit.stderr)] };
  log(`Formatted ${changed.join(", ")}; committed as "style: format".`);
  return null;
}

/**
 * Merges dev into the branch at `top`, release notes by kind and generated
 * API contracts written again. Resolves null once merged, else the exit code
 * and report: 2 leaves a conflicting merge in progress to resolve.
 * @param {ReturnType<typeof gitIn>} git
 * @param {string} top
 * @param {Deps["run"]} run
 * @param {Deps["log"]} log
 * @returns {Promise<{ code: number, report: string[] } | null>}
 */
export async function mergeDev(git, top, run, log) {
  const out = (/** @type {string[]} */ ...args) => git(args).stdout.trim();
  const finish = (
    /** @type {number} */ code,
    /** @type {string[]} */ ...report
  ) => ({ code, report });
  // The notes merge reads what dev's CHANGELOG.md has released.
  const notes = `"${process.execPath}" "${path.join(import.meta.dirname, "changelog.mjs")}" merge %O %A %B ${out("rev-parse", "--verify", "dev")}`;
  const merge = git([
    "-c",
    "merge.dazedtl-notes.name=DazedTL release notes",
    "-c",
    `merge.dazedtl-notes.driver=${notes}`,
    "merge",
    "--no-edit",
    "dev",
  ]);
  if (merge.status !== 0) {
    const conflicted = lines(out("diff", "--name-only", "--diff-filter=U"));
    const abort = () => {
      if (git(["rev-parse", "-q", "--verify", "MERGE_HEAD"]).status === 0)
        git(["merge", "--abort"]);
    };
    if (!conflicted.length) {
      abort();
      return finish(
        1,
        tail(merge.stdout + merge.stderr),
        "Merging dev failed.",
      );
    }
    const resolve = "merge dev and resolve the conflicts, then land again";
    // The merge stays in progress, release notes already merged by kind, so
    // only these files need resolving; a merge run again by hand would merge
    // the notes as text.
    if (!conflicted.every((file) => generated.includes(file)))
      return finish(
        2,
        `Merging dev conflicts in ${conflicted.join(", ")}. The merge is left in progress with everything else merged: resolve these files, commit, and land again.`,
        // Why the notes merge refused, as changelog.mjs printed it.
        ...lines(merge.stdout + merge.stderr).filter((line) =>
          line.startsWith(NOTES),
        ),
      );
    log(
      `Merging dev conflicts only in generated ${conflicted.join(", ")}; writing them again.`,
    );
    git(["checkout", "--theirs", "--", ...conflicted]);
    const written = await run(top, process.execPath, ["scripts/contracts.mjs"]);
    if (written.status !== 0) {
      abort();
      return finish(
        2,
        tail(written.output),
        `node scripts/contracts.mjs failed after merging dev: ${resolve}.`,
      );
    }
    git(["add", "--", ...generated]);
    const commit = git(["commit", "--no-edit"]);
    if (commit.status !== 0) {
      abort();
      return finish(1, tail(commit.stdout + commit.stderr));
    }
  }
  return null;
}

/**
 * The landing itself, while this session holds the lock.
 * @param {Deps} deps
 * @param {{ top: string, main: string, branch: string }} where
 * @param {ReturnType<typeof timer>} time
 * @param {(line: string) => void} tell
 * @returns {Promise<{ code: number, report: string[] }>}
 */
async function underLock(deps, { top, main, branch }, time, tell) {
  const { run, log, wait } = deps;
  const git = gitIn(top);
  const atMain = gitIn(main);
  const out = (/** @type {string[]} */ ...args) => git(args).stdout.trim();
  const finish = (
    /** @type {number} */ code,
    /** @type {string[]} */ ...report
  ) => ({ code, report });
  time.lap("lock wait");
  const before = out("rev-parse", "dev");

  const merged = await mergeDev(git, top, run, log);
  if (merged) return merged;
  const head = out("rev-parse", "HEAD");
  time.lap("merge");
  if (head === before)
    return finish(0, `dev already has every commit of ${branch}.`);

  log("Running node scripts/test.mjs…");
  const tests = await testsWithRetry(
    () => run(top, process.execPath, ["scripts/test.mjs"]),
    deps,
  );
  const lastRun = tests.outputs[tests.outputs.length - 1];
  if (!tests.passed)
    return finish(
      1,
      failureReport(lastRun),
      `node scripts/test.mjs failed twice; fix it on ${branch} and land again.`,
    );
  if (tests.flaky)
    log(
      `Flaky: node scripts/test.mjs failed once and passed when run again; the first run:\n${failureReport(tests.outputs[0], 15)}`,
    );
  time.lap("test");
  const runtime = lastRun.match(/^Full test suite: .*$/m);
  if (runtime) log(runtime[0]);

  // The build is deterministic, so a failure is never run again.
  log("Running node scripts/build.mjs…");
  const build = await run(top, process.execPath, ["scripts/build.mjs"]);
  if (build.status !== 0)
    return finish(
      1,
      tail(build.output),
      `node scripts/build.mjs failed; fix it on ${branch} and land again.`,
    );
  time.lap("build");

  // The fast-forward rewrites the files the user's DazedTL runs from.
  if (await waitForApp(main, deps, tell)) time.lap("app wait");

  const checkedOut = atMain([
    "symbolic-ref",
    "--quiet",
    "--short",
    "HEAD",
  ]).stdout.trim();
  if (checkedOut !== "dev")
    return finish(
      1,
      `${main} has ${checkedOut || "a detached HEAD"} checked out instead of dev; nothing landed.`,
    );
  const changes = atMain([
    "status",
    "--porcelain",
    "--untracked-files=no",
  ]).stdout.trimEnd();
  if (changes)
    return finish(
      1,
      `${main} has uncommitted changes; nothing landed:\n${changes}`,
    );
  // Never replace a file the main checkout ignores, such as local settings.
  const forward = atMain(["merge", "--ff-only", "--no-overwrite-ignore", head]);
  if (forward.status !== 0)
    return finish(
      1,
      tail(forward.stdout + forward.stderr),
      atMain(["merge-base", "--is-ancestor", "dev", head]).status === 0
        ? `dev could not move to ${head.slice(0, 7)}; nothing landed.`
        : "dev moved without the landing lock; land again.",
    );

  const pushUrls = lines(
    atMain(["remote", "get-url", "--push", "--all", "all"]).stdout,
  );
  /** @type {string[]} */
  const unpushed = [];
  for (const target of pushTargets(mirrors(main), pushUrls)) {
    const push = () =>
      run(main, "git", ["push", target.url, "dev"], pushTimeout);
    let pushed = await push();
    if (pushed.status !== 0) {
      log(
        `Pushing dev to ${target.name} failed; trying again in ${pushRetry / 1000} s.`,
      );
      await wait(pushRetry);
      pushed = await push();
    }
    if (pushed.status !== 0)
      unpushed.push(
        `${target.name} (${target.url}):\n${tail(pushed.output, 5)}`,
      );
  }
  time.lap("push");

  const subjects = lines(
    out("log", "--no-merges", "--format=%s", `${before}..${head}`),
  );
  return {
    code: 0,
    report: [
      `Landed ${before.slice(0, 7)}..${head.slice(0, 7)} on dev`,
      ...subjects.map((subject) => `  ${subject}`),
      ...(unpushed.length
        ? [
            `dev did not reach ${unpushed.length === 1 ? "this mirror" : "these mirrors"}; push it there later:`,
            ...unpushed,
          ]
        : []),
    ],
  };
}

/** @returns {Deps} */
function realDeps() {
  /** @type {import("node:child_process").ChildProcess | null} */
  let child = null;
  const token = ghToken();
  return {
    run: (cwd, command, args, timeout) =>
      new Promise((resolve) => {
        /** @type {Buffer[]} */
        const output = [];
        const started = spawn(command, args, {
          cwd,
          // A push that asks for a password fails instead of waiting.
          env: { ...process.env, GIT_TERMINAL_PROMPT: "0" },
          stdio: ["ignore", "pipe", "pipe"],
          timeout,
        });
        child = started;
        started.stdout.on("data", (chunk) => output.push(chunk));
        started.stderr.on("data", (chunk) => output.push(chunk));
        started.on("error", (error) => output.push(Buffer.from(error.message)));
        started.on("close", (status) => {
          child = null;
          resolve({
            status: status ?? 1,
            output: Buffer.concat(output).toString("utf8"),
          });
        });
      }),
    processes: () =>
      spawnSync("ps", ["-eo", "args"], { encoding: "utf8" }).stdout ?? "",
    read: token ? githubReader({ token, log: console.log }) : null,
    wait: sleep,
    log: (line) => console.log(line),
    notify: notifyDesktop,
    onStop: () => child?.kill("SIGTERM"),
  };
}

if (import.meta.main) {
  if (process.argv.length > 2) {
    console.error("Usage: node scripts/land.mjs");
    process.exit(1);
  }
  process.exitCode = await land(process.cwd(), realDeps());
}
