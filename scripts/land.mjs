// Lands a finished branch on dev from its worktree, one landing at a time:
// merges dev in, runs the tests and build, fast-forwards the main checkout's
// dev and pushes it to every mirror. CI then runs on dev; a dev build that
// failed again after one rerun stops the next landing, whose session fixes it
// and lands with --fix-ci. See "Landing" in docs/development.md.
//
//   node scripts/land.mjs [--fix-ci]
//
// Exits 0 when landed, 1 when refused or a check failed, 2 on a merge
// conflict and 4 when this session now owns a red dev build.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import {
  failedJobs,
  failedRun,
  firstFailure,
  ghToken,
  githubReader,
  githubWriter,
  workflow,
} from "./ci-wait.mjs";
import { generated } from "./contracts.mjs";
import { repository } from "./release.mjs";
import { mirrors } from "./update.mjs";

const lockAge = 20 * 60_000;
const claimAge = 2 * 60 * 60_000;
const lockPoll = 3000;
const appPoll = 30_000;
const pushRetry = 60_000;

/** @typedef {{ pid: number, pidNamespace: string | null, branch: string, worktree: string, started: string }} Holder */

/** This process's PID namespace, so a sandboxed lander's PID is not misread. */
export function pidNamespace() {
  try {
    return fs.readlinkSync("/proc/self/ns/pid");
  } catch {
    return null;
  }
}

export function processAlive(/** @type {number} */ pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return /** @type {NodeJS.ErrnoException} */ (error).code === "EPERM";
  }
}

/** @returns {Holder | null} */
function readHolder(/** @type {string} */ dir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(dir, "owner.json"), "utf8"));
  } catch {
    return null;
  }
}

const sameHolder = (/** @type {unknown} */ a, /** @type {unknown} */ b) =>
  JSON.stringify(a) === JSON.stringify(b);

/**
 * Whether a lock's holder has gone or held it too long. A holder in another
 * PID namespace, such as another sandbox, is judged by age alone.
 * @param {Holder | null} holder
 * @param {{ now: () => number, alive: (pid: number) => boolean, namespace: string | null }} context
 */
export function staleHolder(holder, { now, alive, namespace }) {
  if (!holder || typeof holder.pid !== "number") return true;
  if (!(now() - Date.parse(holder.started) < lockAge)) return true;
  return holder.pidNamespace === namespace && !alive(holder.pid);
}

/**
 * Takes the lock folder `dir` for `owner`, waiting while a live holder has
 * it and taking over a stale one. The folder appears whole, owner.json
 * inside, through one rename.
 * @param {string} dir
 * @param {Holder} owner
 * @param {{ now?: () => number, alive?: (pid: number) => boolean, namespace?: string | null, wait?: (ms: number) => Promise<unknown>, log?: (line: string) => void }} [options]
 */
export async function acquireLock(
  dir,
  owner,
  {
    now = Date.now,
    alive = processAlive,
    namespace = pidNamespace(),
    wait = sleep,
    log = () => {},
  } = {},
) {
  fs.mkdirSync(path.dirname(dir), { recursive: true });
  let shown = "";
  for (;;) {
    const staging = `${dir}.${crypto.randomUUID()}`;
    fs.mkdirSync(staging);
    fs.writeFileSync(path.join(staging, "owner.json"), JSON.stringify(owner));
    try {
      fs.renameSync(staging, dir);
      return;
    } catch (error) {
      fs.rmSync(staging, { recursive: true, force: true });
      const code = /** @type {NodeJS.ErrnoException} */ (error).code ?? "";
      if (!["EEXIST", "ENOTEMPTY", "EPERM", "EACCES"].includes(code))
        throw error;
    }
    const holder = readHolder(dir);
    if (staleHolder(holder, { now, alive, namespace })) {
      log(
        `Taking over the landing lock from ${holder ? `${holder.branch} (pid ${holder.pid})` : "an unreadable holder"}, which is gone or held it over ${lockAge / 60_000} min.`,
      );
      steal(dir, holder);
      continue;
    }
    const name = `${holder?.branch} (pid ${holder?.pid}, since ${holder?.started})`;
    if (name !== shown) log(`Waiting for the landing lock, held by ${name}.`);
    shown = name;
    await wait(lockPoll);
  }
}

/** Moves a stale lock aside, and back if another lander took it first. */
function steal(/** @type {string} */ dir, /** @type {Holder | null} */ stale) {
  const aside = `${dir}.stale-${crypto.randomUUID()}`;
  try {
    fs.renameSync(dir, aside);
  } catch {
    return;
  }
  if (!sameHolder(readHolder(aside), stale))
    try {
      fs.renameSync(aside, dir);
      return;
    } catch {
      // A third lander holds it now; the moved holder must take it again.
    }
  fs.rmSync(aside, { recursive: true, force: true });
}

/** Removes the lock when `owner` still holds it. */
export function releaseLock(
  /** @type {string} */ dir,
  /** @type {Holder} */ owner,
) {
  if (sameHolder(readHolder(dir), owner))
    fs.rmSync(dir, { recursive: true, force: true });
}

/**
 * What dev's newest CI runs mean for a landing. A first failed attempt gets
 * one rerun; a failure after that stops the line until a session fixes it,
 * unless another live branch already claimed the fix.
 * @param {{ runs: any[], claim: { branch: string, at: string } | null, branch: string, branchExists: (name: string) => boolean, now: () => number }} state
 * @returns {{ action: "land" | "rerun" | "own" | "warn", run?: any, newer?: any, clear?: boolean }}
 */
export function redBuild({ runs, claim, branch, branchExists, now }) {
  const ordered = [...runs].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const run = ordered.find(
    (item) =>
      item.status === "completed" &&
      !["cancelled", "skipped"].includes(item.conclusion),
  );
  if (!run || !failedRun(run)) return { action: "land", clear: Boolean(claim) };
  // A newer run decides; rerunning this one would cancel it.
  const newer = ordered.find(
    (item) =>
      item.status !== "completed" &&
      Date.parse(item.created_at) > Date.parse(run.created_at),
  );
  if (newer) return { action: "land", run, newer };
  if (firstFailure(run)) return { action: "rerun", run };
  const live =
    claim &&
    now() - Date.parse(claim.at) < claimAge &&
    branchExists(claim.branch);
  if (live && claim.branch !== branch) return { action: "warn", run };
  return { action: "own", run };
}

/** Whether the user's own DazedTL runs from the main checkout. */
export function appRunning(
  /** @type {string} */ main,
  /** @type {string} */ processes,
) {
  const electron = path.join(main, "app", "node_modules", "electron");
  return processes.split("\n").some((line) => line.includes(electron));
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

const tail = (/** @type {string} */ text, lines = 40) =>
  text.trimEnd().split("\n").slice(-lines).join("\n");
const lines = (/** @type {string} */ text) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

/**
 * @typedef {{ status: number, stdout: string, stderr: string }} GitResult
 * @typedef {{
 *   git: (cwd: string, ...args: string[]) => GitResult,
 *   run: (cwd: string, command: string, args: string[]) => Promise<{ status: number, output: string }>,
 *   processes: () => string,
 *   read: ((route: string) => Promise<any>) | null,
 *   post: ((route: string) => Promise<void>) | null,
 *   wait: (ms: number) => Promise<unknown>,
 *   now: () => number,
 *   log: (line: string) => void,
 *   alive?: (pid: number) => boolean,
 *   held?: (release: (() => void) | null) => void,
 * }} Deps
 */

/**
 * Checks dev's CI before landing. Resolves an exit code that stops the
 * landing, or 0 to go on.
 * @param {Deps} deps
 * @param {{ main: string, top: string, branch: string, claimFile: string }} where
 */
async function checkDev(deps, { main, top, branch, claimFile }) {
  const { git, read, post, log, now } = deps;
  const site = mirrors(main).find((mirror) => mirror.type === "github");
  if (!site || !read) {
    log(
      `Landing without checking dev's CI: ${site ? "no GitHub token (set GH_TOKEN or sign in with gh)" : "release/mirrors.json names no GitHub mirror"}.`,
    );
    return 0;
  }
  const repo = new URL(site.url).pathname.replace(/^\/|\.git$/g, "");
  let decision;
  try {
    const found = await read(
      `repos/${repo}/actions/workflows/${path.basename(workflow)}/runs?branch=dev&per_page=10`,
    );
    /** @type {{ branch: string, at: string } | null} */
    let claim = null;
    try {
      claim = JSON.parse(fs.readFileSync(claimFile, "utf8"));
    } catch {
      // No one has claimed a red build.
    }
    decision = redBuild({
      runs: found?.workflow_runs || [],
      claim,
      branch,
      branchExists: (name) =>
        git(top, "show-ref", "--verify", "--quiet", `refs/heads/${name}`)
          .status === 0,
      now,
    });
    if (decision.action === "warn")
      log(
        `CI on dev is red (${decision.run.html_url}); ${claim?.branch} is fixing it, so this lands anyway.`,
      );
  } catch (error) {
    log(
      `Landing without checking dev's CI: ${error instanceof Error ? error.message : String(error)}`,
    );
    return 0;
  }
  const { action, run } = decision;
  if (decision.clear) fs.rmSync(claimFile, { force: true });
  if (decision.newer)
    log(
      `CI on dev failed for ${run.head_sha.slice(0, 7)}; the newer run for ${decision.newer.head_sha.slice(0, 7)} will tell (${decision.newer.html_url}).`,
    );
  if (action === "rerun") {
    try {
      await post?.(`repos/${repo}/actions/runs/${run.id}/rerun-failed-jobs`);
      log(
        `CI on dev failed for ${run.head_sha.slice(0, 7)}; asked GitHub to rerun its failed jobs once (${run.html_url}).`,
      );
    } catch (error) {
      log(
        `CI on dev failed for ${run.head_sha.slice(0, 7)} and GitHub refused a rerun: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  if (action !== "own") return 0;
  let jobs = [];
  try {
    jobs = await failedJobs(read, repo, run);
  } catch {
    // The run's link names them too.
  }
  fs.mkdirSync(path.dirname(claimFile), { recursive: true });
  fs.writeFileSync(
    claimFile,
    `${JSON.stringify(
      {
        branch,
        run: run.id,
        sha: run.head_sha,
        url: run.html_url,
        at: new Date(now()).toISOString(),
      },
      null,
      2,
    )}\n`,
  );
  log(
    [
      `CI on dev failed again after a rerun for ${run.head_sha.slice(0, 7)}${jobs.length ? ` (${jobs.join(", ")})` : ""}: ${run.html_url}`,
      `This session owns the red build. Read the log with: gh run view ${run.id} --repo ${repo} --log-failed`,
      "Fix it forward on this branch, or git revert the commit that broke it here, then run: node scripts/land.mjs --fix-ci",
    ].join("\n"),
  );
  return 4;
}

/**
 * Lands the branch checked out at `cwd`. Resolves the exit code.
 * @param {{ cwd: string, fixCi?: boolean }} options
 * @param {Deps} deps
 */
export async function land({ cwd, fixCi = false }, deps) {
  const { git, log, wait, now } = deps;
  const out = (/** @type {string} */ dir, /** @type {string[]} */ ...args) =>
    git(dir, ...args).stdout.trim();
  const top = out(cwd, "rev-parse", "--show-toplevel");
  const branch = out(top, "symbolic-ref", "--quiet", "--short", "HEAD");
  if (!branch || branch === "dev" || branch === "main") {
    log(
      `Land from a feature branch's worktree, not ${branch || "a detached HEAD"}.`,
    );
    return 1;
  }
  const dirty = out(top, "status", "--porcelain");
  if (dirty) {
    log(`Commit or remove these changes first:\n${dirty}`);
    return 1;
  }
  const common = path.resolve(top, out(top, "rev-parse", "--git-common-dir"));
  const main = path.dirname(common);
  const state = path.join(common, "dazedtl");
  const claimFile = path.join(state, "ci-red.json");

  if (!fixCi) {
    const code = await checkDev(deps, { main, top, branch, claimFile });
    if (code) return code;
  }

  let said = false;
  while (appRunning(main, deps.processes())) {
    if (!said)
      log(
        `Your DazedTL is open from ${main}; this lands when it closes (checking every ${appPoll / 1000} s).`,
      );
    said = true;
    await wait(appPoll);
  }

  const lock = path.join(state, "land.lock");
  /** @type {Holder} */
  const owner = {
    pid: process.pid,
    pidNamespace: pidNamespace(),
    branch,
    worktree: top,
    started: new Date(now()).toISOString(),
  };
  await acquireLock(lock, owner, { now, wait, log, alive: deps.alive });
  deps.held?.(() => releaseLock(lock, owner));
  /** @type {string[]} */
  let report = [];
  let code = 1;
  try {
    ({ code, report } = await underLock(deps, { top, main, branch }));
  } finally {
    releaseLock(lock, owner);
    deps.held?.(null);
  }
  for (const line of report) log(line);
  if (code === 0 && fixCi) {
    /** @type {{ branch?: string } | null} */
    let claim = null;
    try {
      claim = JSON.parse(fs.readFileSync(claimFile, "utf8"));
    } catch {
      // Nothing claimed.
    }
    if (claim?.branch === branch) {
      fs.rmSync(claimFile, { force: true });
      log("Released this branch's claim on the red dev build.");
    } else if (claim) log(`${claim.branch} still claims the red dev build.`);
  }
  return code;
}

/**
 * The landing itself, while this session holds the lock.
 * @param {Deps} deps
 * @param {{ top: string, main: string, branch: string }} where
 * @returns {Promise<{ code: number, report: string[] }>}
 */
async function underLock(deps, { top, main, branch }) {
  const { git, run, log, wait } = deps;
  const out = (/** @type {string} */ dir, /** @type {string[]} */ ...args) =>
    git(dir, ...args).stdout.trim();
  const finish = (
    /** @type {number} */ code,
    /** @type {string[]} */ ...report
  ) => ({
    code,
    report,
  });
  const before = out(top, "rev-parse", "dev");

  const notes = `"${process.execPath}" "${path.join(top, "scripts", "changelog.mjs")}" merge %O %A %B`;
  const merge = git(
    top,
    "-c",
    "merge.dazedtl-notes.name=DazedTL release notes",
    "-c",
    `merge.dazedtl-notes.driver=${notes}`,
    "merge",
    "--no-edit",
    "dev",
  );
  if (merge.status !== 0) {
    const conflicted = lines(
      out(top, "diff", "--name-only", "--diff-filter=U"),
    );
    const abort = () => {
      if (git(top, "rev-parse", "-q", "--verify", "MERGE_HEAD").status === 0)
        git(top, "merge", "--abort");
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
    if (!conflicted.every((file) => generated.includes(file))) {
      abort();
      return finish(
        2,
        `Merging dev conflicts in ${conflicted.join(", ")}: ${resolve}.`,
      );
    }
    log(
      `Merging dev conflicts only in generated ${conflicted.join(", ")}; writing them again.`,
    );
    git(top, "checkout", "--theirs", "--", ...conflicted);
    const written = await run(top, process.execPath, ["scripts/contracts.mjs"]);
    if (written.status !== 0) {
      abort();
      return finish(
        2,
        tail(written.output),
        `node scripts/contracts.mjs failed after merging dev: ${resolve}.`,
      );
    }
    git(top, "add", "--", ...generated);
    const commit = git(top, "commit", "--no-edit");
    if (commit.status !== 0) {
      abort();
      return finish(1, tail(commit.stdout + commit.stderr));
    }
  }
  const head = out(top, "rev-parse", "HEAD");
  if (head === before)
    return finish(0, `dev already has every commit of ${branch}.`);

  for (const script of ["scripts/test.mjs", "scripts/build.mjs"]) {
    log(`Running node ${script}…`);
    const result = await run(top, process.execPath, [script]);
    if (result.status !== 0)
      return finish(
        1,
        tail(result.output),
        `node ${script} failed; fix it on ${branch} and land again.`,
      );
    const runtime = result.output.match(/^Full test suite: .*$/m);
    if (runtime) log(runtime[0]);
  }

  const checkedOut = out(main, "symbolic-ref", "--quiet", "--short", "HEAD");
  if (checkedOut !== "dev")
    return finish(
      1,
      `${main} has ${checkedOut || "a detached HEAD"} checked out instead of dev; nothing landed.`,
    );
  const forward = git(main, "merge", "--ff-only", head);
  if (forward.status !== 0) {
    const moved =
      git(main, "merge-base", "--is-ancestor", "dev", head).status !== 0;
    const changes = out(main, "status", "--porcelain");
    return finish(
      1,
      tail(forward.stdout + forward.stderr),
      moved
        ? "dev moved while this landed without the lock; land again."
        : `dev could not move to ${head.slice(0, 7)}${changes ? `; ${main} has uncommitted changes:\n${changes}` : "."}`,
    );
  }

  const pushUrls = lines(
    out(main, "remote", "get-url", "--push", "--all", "all"),
  );
  /** @type {string[]} */
  const unpushed = [];
  for (const target of pushTargets(mirrors(main), pushUrls)) {
    let pushed = await run(main, "git", ["push", target.url, "dev"]);
    if (pushed.status !== 0) {
      log(
        `Pushing dev to ${target.name} failed; trying again in ${pushRetry / 1000} s.`,
      );
      await wait(pushRetry);
      pushed = await run(main, "git", ["push", target.url, "dev"]);
    }
    if (pushed.status !== 0)
      unpushed.push(
        `${target.name} (${target.url}):\n${tail(pushed.output, 5)}`,
      );
  }

  const subjects = lines(
    out(main, "log", "--no-merges", "--format=%s", `${before}..${head}`),
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
  /** @type {(() => void) | null} */
  let release = null;
  const stop = (/** @type {number} */ code) => {
    child?.kill("SIGTERM");
    release?.();
    process.exit(code);
  };
  process.on("SIGINT", () => stop(130));
  process.on("SIGTERM", () => stop(143));
  process.on("exit", () => release?.());
  const token = ghToken();
  return {
    git: (cwd, ...args) => {
      const result = spawnSync("git", args, { cwd, encoding: "utf8" });
      return {
        status: result.status ?? 1,
        stdout: result.stdout ?? "",
        stderr: result.stderr || result.error?.message || "",
      };
    },
    run: (cwd, command, args) =>
      new Promise((resolve) => {
        /** @type {Buffer[]} */
        const output = [];
        child = spawn(command, args, {
          cwd,
          stdio: ["ignore", "pipe", "pipe"],
          windowsHide: true,
        });
        child.stdout?.on("data", (chunk) => output.push(chunk));
        child.stderr?.on("data", (chunk) => output.push(chunk));
        child.on("error", (error) => output.push(Buffer.from(error.message)));
        child.on("close", (status) => {
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
    post: token ? githubWriter({ token }) : null,
    wait: sleep,
    now: Date.now,
    log: (line) => console.log(line),
    held: (next) => {
      release = next;
    },
  };
}

if (import.meta.main) {
  const args = process.argv.slice(2);
  const unknown = args.filter((arg) => arg !== "--fix-ci");
  if (unknown.length) {
    console.error("Usage: node scripts/land.mjs [--fix-ci]");
    process.exit(1);
  }
  process.exitCode = await land(
    { cwd: process.cwd(), fixCi: args.includes("--fix-ci") },
    realDeps(),
  );
}
