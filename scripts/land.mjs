// Lands a finished branch on dev from its worktree, one landing at a time:
// formats it, merges dev in, runs the tests and build, fast-forwards the main
// checkout's dev and pushes it to every mirror. CI then runs on dev, and the
// session that cuts the next release answers for a run still red. Runs on
// Linux and macOS. A wait on the user's DazedTL or a slow landing lock is
// told to the user on the desktop too, since agents run this in the
// background. Each landing carries a record of the code review a reviewer
// other than its author ran, kept in the shared Git directory to measure what
// reviews catch. See "Landing" in docs/development.md.
//
// A worker that may never write the main checkout, such as a Discord intake
// worker in its own clone, lands in two steps. --hand-off runs the same
// format, merge and checks against origin's dev and leaves the checked branch
// as a bundle and record in <dir>. The intake has the bundle reviewed, then
// --finish, run outside the worker's sandbox by the main checkout's own
// land.mjs, moves dev to it with Git alone.
//
//   node scripts/land.mjs --review <file.json>
//   node scripts/land.mjs --hand-off <dir>
//   node scripts/land.mjs --finish <dir> --review <file.json>
//
// Exits 0 when landed, handed off or with nothing to hand off, 1 when refused
// or a check failed and 2 on a merge conflict. --finish never waits without
// a limit: it exits 3 when dev moved after the hand-off's checks, 4 at once
// while the user's DazedTL runs from the main checkout, and 5 when the main
// checkout cannot take it now, such as while another session holds the lock.
import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { parseArgs } from "node:util";
import {
  failedJobs,
  failedRun,
  ghToken,
  githubReader,
  workflow,
} from "./ci-wait.mjs";
import { NOTES } from "./changelog.mjs";
import { generated } from "./contracts.mjs";
import {
  commitFormat,
  finders,
  isFix,
  missingTrailers,
  readCommits,
} from "./fix-trailers.mjs";
import {
  devMoved,
  gitIn,
  LockBusy,
  reviewLog,
  withLock,
} from "./land-lock.mjs";
import { repository } from "./release.mjs";
import { failureReport, tail, testsWithRetry } from "./testkit/retry.mjs";
import { mirrors } from "./update.mjs";

const appPoll = 30_000;
const pushRetry = 60_000;
const pushTimeout = 5 * 60_000;
const icon = path.join(import.meta.dirname, "..", "resources", "icon.png");
/** The code-review levels a landing's review may run at: high and up. */
const reviewLevels = ["high", "xhigh", "max", "ultra"];
/** The most independent reviews one landing runs; the dazedtl-land skill says when another runs. */
const maxReviews = 3;
/**
 * What a finding is: a bug its reviewer showed with a failing test or a
 * command's output, a risk it could not show, or quality such as wording,
 * docs, naming or design. Older and intake records leave it out.
 */
export const findingKinds = ["bug", "risk", "quality"];
const reviewShape =
  '{"level": "high", "reviewer": "independent", "reviews": 1, "head": "<hash of the last commit the last reviewer checked>", "findings": [{"summary": "...", "kind": "bug", "outcome": "fixed", "review": 1}, {"summary": "...", "kind": "quality", "outcome": "dismissed", "reason": "...", "review": 1}]}';
/** The subject of the commit holding what the formatter changed. */
const formatSubject = "style: format";
/** Where a hand-off's worker keeps origin's dev in its clone. */
const originDev = "refs/remotes/origin/dev";
/** The files a hand-off leaves in its directory for --finish. */
const handoffRecord = "handoff.json";
const handoffBundle = "handoff.bundle";
/** Where --finish fetches a hand-off's branch while it checks it. */
const handoffRef = "refs/dazedtl/handoff";
/** Keeps hooks and the file system monitor from running while --finish works. */
const sealed = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"];
/** --finish's exit codes for a hand-off to retry later, beside devMoved. */
const appOpen = 4;
const mainBusy = 5;
/** How long --finish waits for another session's landing lock. */
const lockLimit = 10 * 60_000;

/**
 * Reads a landing's review record: the code-review level a reviewer that
 * never saw the work ran, how many such reviews ran (1 when not given), the
 * last commit the last one checked and what became of each finding, with
 * the review that reported it, which only a one-review record may leave out,
 * and its kind (findingKinds), which only the Discord intake's records may
 * leave out, so `kinds` asks for it everywhere else.
 * Throws with what is wrong, so no branch lands on its author's review alone.
 * @param {string} text
 * @param {{ kinds?: boolean }} [options]
 * @returns {{ level: string, reviewer: "independent", reviews: number, head: string, findings: { summary: string, kind?: string, outcome: "fixed" | "dismissed", reason?: string, review: number }[] }}
 */
export function readReview(text, { kinds = false } = {}) {
  let record;
  try {
    record = JSON.parse(text);
  } catch (error) {
    throw new Error(`The review record is not JSON: ${reason(error)}`);
  }
  const filled = (/** @type {unknown} */ value) =>
    typeof value === "string" && value.trim() !== "";
  // A count of reviews, or the number of one of them, from 1 to `most`.
  const counted = (/** @type {unknown} */ value, /** @type {number} */ most) =>
    Number.isInteger(value) && Number(value) >= 1 && Number(value) <= most;
  if (record?.reviewer !== "independent")
    throw new Error(
      'The review record needs "reviewer": "independent": a reviewer that never saw the work reviews every landing, not its author (Landing in docs/development.md).',
    );
  if (!reviewLevels.includes(record.level))
    throw new Error(
      `The review record needs a level of ${reviewLevels.join(", ")}.`,
    );
  const reviews = record.reviews === undefined ? 1 : record.reviews;
  if (!counted(reviews, maxReviews))
    throw new Error(
      `The review record needs "reviews", how many independent reviews ran, from 1 to ${maxReviews}.`,
    );
  // A name such as HEAD would follow the branch past what was reviewed.
  if (typeof record.head !== "string" || !/^[0-9a-f]{7,64}$/i.test(record.head))
    throw new Error(
      "The review record needs the hash of the head commit its last reviewer checked.",
    );
  if (!Array.isArray(record.findings))
    throw new Error(
      "The review record needs a findings list, empty when the review found nothing.",
    );
  const findings = record.findings.map(
    (/** @type {any} */ item, /** @type {number} */ index) => {
      const which = `Finding ${index + 1} of the review record`;
      if (!filled(item?.summary)) throw new Error(`${which} needs a summary.`);
      const review =
        item.review === undefined && reviews === 1 ? 1 : item.review;
      if (!counted(review, reviews))
        throw new Error(
          `${which} needs a review number from 1 to ${reviews}: the independent review that reported it, with "reviews" saying how many ran when more than one did.`,
        );
      if (
        (kinds || item.kind !== undefined) &&
        !findingKinds.includes(item.kind)
      )
        throw new Error(`${which} needs a kind of ${findingKinds.join(", ")}.`);
      const kind = item.kind === undefined ? {} : { kind: item.kind };
      if (item.outcome === "fixed")
        return { summary: item.summary, ...kind, outcome: "fixed", review };
      if (item.outcome !== "dismissed")
        throw new Error(`${which} needs an outcome of fixed or dismissed.`);
      if (!filled(item.reason))
        throw new Error(`${which} is dismissed without a reason.`);
      return {
        summary: item.summary,
        ...kind,
        outcome: "dismissed",
        reason: item.reason,
        review,
      };
    },
  );
  return {
    level: record.level,
    reviewer: "independent",
    reviews,
    head: record.head,
    findings,
  };
}

/**
 * Resolves the commit a landing's reviewer last checked to its full hash.
 * Throws when it is not on the branch at `git`, or when the branch has
 * commits of its own after it: apart from merges of dev and the formatter's
 * commits, a change made after the review lands only once it is reviewed.
 * @param {ReturnType<typeof gitIn>} git
 * @param {string} head
 */
export function reviewedHead(git, head) {
  const commit = git([
    "rev-parse",
    "--verify",
    "--quiet",
    `${head}^{commit}`,
  ]).stdout.trim();
  if (
    !commit ||
    git(["merge-base", "--is-ancestor", commit, "HEAD"]).status !== 0
  )
    throw new Error(
      `The review record's head ${head} is not a commit on this branch.`,
    );
  const onDev = (/** @type {string} */ parent) =>
    git(["merge-base", "--is-ancestor", parent, "dev"]).status === 0;
  const after = lines(
    git(["log", "--first-parent", "--format=%P\t%h %s", `${commit}..HEAD`])
      .stdout,
  ).flatMap((line) => {
    const [parents, title] = line.split("\t", 2);
    const merged = parents.split(" ").slice(1);
    const reviewed = merged.length
      ? merged.every(onDev)
      : title.slice(title.indexOf(" ") + 1) === formatSubject;
    return reviewed ? [] : [title];
  });
  if (after.length)
    throw new Error(
      `These commits came after the review record's head; have the reviewer check them and record the new head:\n${after.join("\n")}`,
    );
  return commit;
}

/**
 * Says which of the branch's own fix commits after `base`, merges left out
 * since those bring in what other landings checked, end without the
 * trailers AGENTS.md asks for (fix-trailers.mjs) or name a commit that is
 * not before them, ending with `then`; null when none do.
 * @param {ReturnType<typeof gitIn>} git
 * @param {string} base
 * @param {string} [then] what to do once they carry them
 * @returns {string | null}
 */
export function untrailedFixes(git, base, then = "") {
  const listed = git([
    "log",
    "--no-merges",
    `--format=${commitFormat}`,
    `${base}..HEAD`,
  ]);
  if (listed.status !== 0)
    return `Git can't list the branch's commits: ${listed.stderr.trim()}`;
  const untrailed = readCommits(listed.stdout)
    .filter((commit) => isFix(commit.subject))
    .flatMap((commit) => {
      const lacks = missingTrailers(commit);
      for (const hash of commit.hashes) {
        const named = git([
          "rev-parse",
          "--verify",
          "--quiet",
          `${hash}^{commit}`,
        ]).stdout.trim();
        if (!named)
          lacks.push(
            `Introduced-by ${hash} names no commit Git can find, or several; give more of the hash`,
          );
        else if (
          named === commit.commit ||
          git(["merge-base", "--is-ancestor", named, commit.commit]).status !==
            0
        )
          lacks.push(`Introduced-by ${hash} names no commit before it`);
      }
      return lacks.length
        ? [
            `${commit.commit.slice(0, 7)} ${commit.subject}: ${lacks.join("; ")}`,
          ]
        : [];
    });
  if (!untrailed.length) return null;
  return [
    "These fix commits lack the trailers AGENTS.md asks for:",
    ...untrailed,
    `End each one's message, after a blank line, with "Introduced-by: <hash>" naming the commit that brought the bug in, this branch's own included, or "Introduced-by: unknown" when the history doesn't show it or "none" when no commit did, and with "Found-by: <who>", one of ${finders.join(", ")}. Reword the last commit with git commit --amend. A rebase that rewords an earlier one gives each commit after it a new hash, so change an Introduced-by naming one of those to its new hash.${then && ` ${then}`}`,
  ].join("\n");
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

/** @typedef {{ code: number, report: string[] }} Outcome */

/** An exit code and the lines that report it. @returns {Outcome} */
const outcome = (
  /** @type {number} */ code,
  /** @type {string[]} */ ...report
) => ({ code, report });

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

/** Refuses to run on Windows, saying so. */
export function onWindows(/** @type {Deps["log"]} */ log) {
  if (process.platform !== "win32") return false;
  log("Land from Linux or macOS; land.mjs does not run on Windows.");
  return true;
}

/**
 * The feature branch checked out at `cwd`, with every change committed.
 * Returns exit code 1 instead, saying why, when it is not one.
 * @param {string} cwd
 * @param {Deps["log"]} log
 * @returns {{ top: string, git: ReturnType<typeof gitIn>, branch: string } | number}
 */
function featureBranch(cwd, log) {
  const top = gitIn(cwd)(["rev-parse", "--show-toplevel"]).stdout.trim();
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
  return { top, git, branch };
}

/** Prints an outcome's report and where the minutes went. Returns its code. */
function reported(
  /** @type {Deps} */ { log },
  /** @type {Outcome} */ result,
  /** @type {ReturnType<typeof timer>} */ time,
) {
  for (const line of result.report) log(line);
  log(time.summary());
  return result.code;
}

/**
 * Runs `task` holding the landing lock and reports its outcome. A wait on
 * something outside it reaches the user on the desktop, and its line is
 * marked for an agent watching the output. With `limit`, a lock held longer
 * than that by another session ends it with exit code 5. Resolves the code.
 * @param {Deps} deps
 * @param {ReturnType<typeof gitIn>} git
 * @param {{ branch: string, worktree: string }} who
 * @param {ReturnType<typeof timer>} time
 * @param {(tell: (line: string) => void) => Promise<Outcome>} task
 * @param {number} [limit]
 */
async function lockedRun(deps, git, who, time, task, limit) {
  const tell = (/** @type {string} */ line) => {
    deps.log(`Notice: ${line}`);
    deps.notify(`Landing ${who.branch}`, line);
  };
  let result;
  try {
    result = await withLock(git, who, () => task(tell), {
      log: deps.log,
      notify: tell,
      onStop: deps.onStop,
      limit,
    });
  } catch (error) {
    if (!(error instanceof LockBusy)) throw error;
    result = outcome(
      mainBusy,
      `${error.message} Nothing changed; try again later.`,
    );
  }
  return reported(deps, result, time);
}

/**
 * Lands the branch checked out at `cwd`. Resolves the exit code.
 * @param {string} cwd
 * @param {Deps} deps
 * @param {string | undefined} reviewFile the review record's path
 */
export async function land(cwd, deps, reviewFile) {
  const { log } = deps;
  if (onWindows(log)) return 1;
  if (!reviewFile) {
    log(
      `Land with --review <file.json> holding the branch's independent code review: ${reviewShape}.`,
    );
    return 1;
  }
  let review;
  try {
    review = readReview(fs.readFileSync(reviewFile, "utf8"), { kinds: true });
  } catch (error) {
    log(`${reason(error)} Expected: ${reviewShape}.`);
    return 1;
  }
  const found = featureBranch(cwd, log);
  if (typeof found === "number") return found;
  const { top, git, branch } = found;
  const untrailed = untrailedFixes(
    git,
    "refs/heads/dev",
    "Then record the new head in the review record.",
  );
  if (untrailed) {
    log(untrailed);
    return 1;
  }
  try {
    review = { ...review, head: reviewedHead(git, review.head) };
  } catch (error) {
    log(reason(error));
    return 1;
  }
  const common = path.resolve(
    top,
    git(["rev-parse", "--git-common-dir"]).stdout.trim(),
  );
  const main = path.dirname(common);
  await warnRedDev(deps, main);
  const time = timer(deps.now);
  const unformatted = await formatBranch(git, top, deps.run, log);
  if (unformatted) {
    for (const line of unformatted.report) log(line);
    return unformatted.code;
  }
  time.lap("format");
  return lockedRun(deps, git, { branch, worktree: top }, time, (tell) =>
    underLock(deps, { top, main, branch }, time, tell, (range) =>
      recordReview(deps, common, { branch, range, review }),
    ),
  );
}

/**
 * Adds a landed range's review to the reviews log in the shared Git
 * directory `common`. dev has moved by then, so a lost record never stops the
 * pushes.
 * @param {Deps} deps
 * @param {string} common
 * @param {{ branch: string, range: string, review: ReturnType<typeof readReview> }} landed
 */
function recordReview({ log, now }, common, { branch, range, review }) {
  try {
    fs.appendFileSync(
      path.join(common, reviewLog),
      `${JSON.stringify({ landed: new Date(now?.() ?? Date.now()).toISOString(), branch, range, ...review })}\n`,
    );
  } catch (error) {
    log(`Could not record the review: ${reason(error)}`);
  }
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
 * @returns {Promise<Outcome | null>}
 */
export async function formatBranch(git, top, run, log) {
  const formatted = await run(top, process.execPath, ["scripts/format.mjs"]);
  if (formatted.status !== 0)
    return outcome(
      1,
      tail(formatted.output),
      "node scripts/format.mjs failed.",
    );
  const changed = lines(git(["diff", "--name-only"]).stdout);
  if (!changed.length) return null;
  git(["add", "--update"]);
  const commit = git([
    "commit",
    "--quiet",
    "-m",
    formatSubject,
    "-m",
    `- Format ${changed.join(", ")} as format.mjs does`,
  ]);
  if (commit.status !== 0)
    return outcome(1, tail(commit.stdout + commit.stderr));
  log(`Formatted ${changed.join(", ")}; committed as "${formatSubject}".`);
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
 * @param {string} [dev] the ref holding dev, such as a hand-off's origin/dev
 * @returns {Promise<Outcome | null>}
 */
export async function mergeDev(git, top, run, log, dev = "dev") {
  const out = (/** @type {string[]} */ ...args) => git(args).stdout.trim();
  // The notes merge reads what dev's CHANGELOG.md has released.
  const notes = `"${process.execPath}" "${path.join(import.meta.dirname, "changelog.mjs")}" merge %O %A %B ${out("rev-parse", "--verify", dev)}`;
  const merge = git([
    "-c",
    "merge.dazedtl-notes.name=DazedTL release notes",
    "-c",
    `merge.dazedtl-notes.driver=${notes}`,
    "merge",
    "--no-edit",
    dev,
  ]);
  if (merge.status !== 0) {
    const conflicted = lines(out("diff", "--name-only", "--diff-filter=U"));
    const abort = () => {
      if (git(["rev-parse", "-q", "--verify", "MERGE_HEAD"]).status === 0)
        git(["merge", "--abort"]);
    };
    if (!conflicted.length) {
      abort();
      return outcome(
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
      return outcome(
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
      return outcome(
        2,
        tail(written.output),
        `node scripts/contracts.mjs failed after merging dev: ${resolve}.`,
      );
    }
    git(["add", "--", ...generated]);
    const commit = git(["commit", "--no-edit"]);
    if (commit.status !== 0) {
      abort();
      return outcome(1, tail(commit.stdout + commit.stderr));
    }
  }
  return null;
}

/**
 * Runs the tests, once more when they fail, and the build on the branch at
 * `top`. Resolves null when both pass, else the exit code and report.
 * @param {Deps} deps
 * @param {string} top
 * @param {string} branch
 * @param {ReturnType<typeof timer>} time
 * @returns {Promise<Outcome | null>}
 */
async function runChecks(deps, top, branch, time) {
  const { run, log } = deps;
  log("Running node scripts/test.mjs…");
  const tests = await testsWithRetry(
    () => run(top, process.execPath, ["scripts/test.mjs"]),
    deps,
  );
  const lastRun = tests.outputs[tests.outputs.length - 1];
  if (!tests.passed)
    return outcome(
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
    return outcome(
      1,
      tail(build.output),
      `node scripts/build.mjs failed; fix it on ${branch} and land again.`,
    );
  time.lap("build");
  return null;
}

/**
 * Where dev is pushed: the mirrors the main checkout's release/mirrors.json
 * names, at the "all" remote's push URLs. Read before dev moves, so a branch
 * never chooses where its own landing is pushed.
 * @param {ReturnType<typeof gitIn>} atMain
 * @param {string} main
 */
function mirrorTargets(atMain, main) {
  const pushUrls = lines(
    atMain(["remote", "get-url", "--push", "--all", "all"]).stdout,
  );
  return pushTargets(mirrors(main), pushUrls);
}

/**
 * Fast-forwards the main checkout's dev to `head`. Returns null once it
 * moved, else why not: "busy" while the main checkout is off dev or has
 * changes, which clears by itself; "moved" when dev moved past the landing;
 * "refused" when Git refuses the branch's files there, such as one that
 * would replace a file the main checkout ignores or has untracked.
 * @param {ReturnType<typeof gitIn>} atMain
 * @param {string} main
 * @param {string} head
 * @returns {{ cause: "busy" | "moved" | "refused", report: string[] } | null}
 */
function moveDev(atMain, main, head) {
  const checkedOut = atMain([
    "symbolic-ref",
    "--quiet",
    "--short",
    "HEAD",
  ]).stdout.trim();
  if (checkedOut !== "dev")
    return {
      cause: "busy",
      report: [
        `${main} has ${checkedOut || "a detached HEAD"} checked out instead of dev; nothing landed.`,
      ],
    };
  const changes = atMain([
    "status",
    "--porcelain",
    "--untracked-files=no",
  ]).stdout.trimEnd();
  if (changes)
    return {
      cause: "busy",
      report: [`${main} has uncommitted changes; nothing landed:\n${changes}`],
    };
  // Never replace a file the main checkout ignores, such as local settings.
  const forward = atMain(["merge", "--ff-only", "--no-overwrite-ignore", head]);
  if (forward.status === 0) return null;
  const why = tail(forward.stdout + forward.stderr);
  return atMain(["merge-base", "--is-ancestor", "dev", head]).status === 0
    ? {
        cause: "refused",
        report: [
          why,
          `dev could not move to ${head.slice(0, 7)}; nothing landed.`,
        ],
      }
    : {
        cause: "moved",
        report: [why, "dev moved without the landing lock; land again."],
      };
}

/**
 * Pushes the main checkout's dev to each target, once more after a minute
 * when a push fails. Resolves the mirrors it did not reach.
 * @param {Deps} deps
 * @param {string} main
 * @param {{ name: string, url: string }[]} targets
 * @param {string[]} [options] Git options for each push
 */
async function pushDev({ run, log, wait }, main, targets, options = []) {
  /** @type {string[]} */
  const unpushed = [];
  for (const target of targets) {
    const push = () =>
      run(main, "git", [...options, "push", target.url, "dev"], pushTimeout);
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
  return unpushed;
}

/**
 * Reports a landed range, its commits and any mirror dev did not reach.
 * @param {ReturnType<typeof gitIn>} git
 * @param {string} before
 * @param {string} head
 * @param {string[]} unpushed
 */
function landed(git, before, head, unpushed) {
  const subjects = lines(
    git(["log", "--no-merges", "--format=%s", `${before}..${head}`]).stdout,
  );
  return outcome(
    0,
    `Landed ${before.slice(0, 7)}..${head.slice(0, 7)} on dev`,
    ...subjects.map((subject) => `  ${subject}`),
    ...(unpushed.length
      ? [
          `dev did not reach ${unpushed.length === 1 ? "this mirror" : "these mirrors"}; push it there later:`,
          ...unpushed,
        ]
      : []),
  );
}

/**
 * The landing itself, while this session holds the lock.
 * @param {Deps} deps
 * @param {{ top: string, main: string, branch: string }} where
 * @param {ReturnType<typeof timer>} time
 * @param {(line: string) => void} tell
 * @param {(range: string) => void} record records the review of a landed range
 * @returns {Promise<Outcome>}
 */
async function underLock(deps, { top, main, branch }, time, tell, record) {
  const { run, log } = deps;
  const git = gitIn(top);
  const atMain = gitIn(main);
  const out = (/** @type {string[]} */ ...args) => git(args).stdout.trim();
  time.lap("lock wait");
  const before = out("rev-parse", "dev");

  const merged = await mergeDev(git, top, run, log);
  if (merged) return merged;
  const head = out("rev-parse", "HEAD");
  time.lap("merge");
  if (head === before)
    return outcome(0, `dev already has every commit of ${branch}.`);
  const failed = await runChecks(deps, top, branch, time);
  if (failed) return failed;

  // The fast-forward rewrites the files the user's DazedTL runs from.
  if (await waitForApp(main, deps, tell)) time.lap("app wait");
  const targets = mirrorTargets(atMain, main);
  const refused = moveDev(atMain, main, head);
  if (refused) return outcome(1, ...refused.report);
  // dev has the commits now, whether or not every mirror takes them.
  record(`${before}..${head}`);
  const unpushed = await pushDev(deps, main, targets);
  time.lap("push");
  return landed(git, before, head, unpushed);
}

/**
 * Hands off the branch checked out in a worker's clone at `cwd`: formats it,
 * merges origin's dev into it and runs the tests and build, then leaves its
 * commits since that dev in `dir` as a bundle and a record for --finish.
 * Writes nothing outside the clone and `dir`. Resolves the exit code.
 * @param {string} cwd
 * @param {Deps} deps
 * @param {string | undefined} dir
 */
export async function handOff(cwd, deps, dir) {
  const { log } = deps;
  if (onWindows(log)) return 1;
  if (!dir) {
    log("Hand off with --hand-off <dir>, the directory your prompt gives.");
    return 1;
  }
  // A hand-off that fails never leaves an earlier one behind to finish.
  try {
    fs.mkdirSync(dir, { recursive: true });
    for (const name of [handoffRecord, handoffBundle])
      fs.rmSync(path.join(dir, name), { force: true });
  } catch (error) {
    log(`Could not prepare ${dir} for the hand-off: ${reason(error)}`);
    return 1;
  }
  const found = featureBranch(cwd, log);
  if (typeof found === "number") return found;
  const { top, git, branch } = found;
  // The clone may never write the main repository, so it checks against
  // origin's dev, fetched into the clone.
  const fetched = git([
    "fetch",
    "--quiet",
    "--no-tags",
    "origin",
    `+refs/heads/dev:${originDev}`,
  ]);
  if (fetched.status !== 0) {
    log(tail(fetched.stdout + fetched.stderr));
    log("Fetching dev from origin failed; nothing was handed off.");
    return 1;
  }
  const untrailed = untrailedFixes(git, originDev, "Then hand off again.");
  if (untrailed) {
    log(untrailed);
    return 1;
  }
  const time = timer(deps.now);
  return reported(
    deps,
    await handOffBranch(deps, { top, git, branch, dir }, time),
    time,
  );
}

/**
 * A hand-off's checks and output, once origin's dev is fetched.
 * @param {Deps} deps
 * @param {{ top: string, git: ReturnType<typeof gitIn>, branch: string, dir: string }} where
 * @param {ReturnType<typeof timer>} time
 * @returns {Promise<Outcome>}
 */
async function handOffBranch(deps, { top, git, branch, dir }, time) {
  const { run, log } = deps;
  const out = (/** @type {string[]} */ ...args) => git(args).stdout.trim();
  const unformatted = await formatBranch(git, top, run, log);
  if (unformatted) return unformatted;
  time.lap("format");
  const base = out("rev-parse", "--verify", `${originDev}^{commit}`);
  const merged = await mergeDev(git, top, run, log, originDev);
  if (merged) return merged;
  const head = out("rev-parse", "HEAD");
  time.lap("merge");
  if (head === base)
    return outcome(
      0,
      `Nothing to hand off: dev already has ${head.slice(0, 7)}`,
    );
  const failed = await runChecks(deps, top, branch, time);
  if (failed) return failed;

  const bundled = git([
    "bundle",
    "create",
    path.resolve(dir, handoffBundle),
    `refs/heads/${branch}`,
    `^${base}`,
  ]);
  if (bundled.status !== 0)
    return outcome(
      1,
      tail(bundled.stdout + bundled.stderr),
      "Writing the hand-off's bundle failed; nothing was handed off.",
    );
  const record = path.join(dir, handoffRecord);
  try {
    // --finish never reads a record half written.
    fs.writeFileSync(
      `${record}.tmp`,
      `${JSON.stringify({ format: 1, branch, head, base }, null, 2)}\n`,
    );
    fs.renameSync(`${record}.tmp`, record);
  } catch (error) {
    return outcome(
      1,
      `Could not write the hand-off's record: ${reason(error)}`,
    );
  }
  return outcome(0, `Handed off ${base.slice(0, 7)}..${head.slice(0, 7)}`);
}

/**
 * Reads a hand-off's record. Throws with what is wrong.
 * @param {string} text
 * @returns {{ branch: string, head: string, base: string }}
 */
export function readHandoff(text) {
  let record;
  try {
    record = JSON.parse(text);
  } catch (error) {
    throw new Error(`The hand-off's record is not JSON: ${reason(error)}`);
  }
  if (record?.format !== 1)
    throw new Error("The hand-off's record is not of format 1.");
  if (
    typeof record.branch !== "string" ||
    !/^[\w.][\w./-]*$/.test(record.branch) ||
    ["dev", "main"].includes(record.branch)
  )
    throw new Error("The hand-off's record needs its feature branch's name.");
  const hash = (/** @type {unknown} */ value) =>
    typeof value === "string" && /^([0-9a-f]{40}|[0-9a-f]{64})$/.test(value);
  if (!hash(record.head) || !hash(record.base))
    throw new Error(
      "The hand-off's record needs the full hashes of its head and base.",
    );
  return { branch: record.branch, head: record.head, base: record.base };
}

/** Runs Git in `cwd` with no hook or file system monitor. */
function sealedGit(/** @type {string} */ cwd) {
  const git = gitIn(cwd);
  return /** @type {ReturnType<typeof gitIn>} */ (
    (args, input) => git([...sealed, ...args], input)
  );
}

const appOpenLine = (/** @type {string} */ main) =>
  `Your DazedTL is open from ${main}; nothing landed. Finish again once it closes.`;

/**
 * Lands the hand-off in `dir` on the main checkout's dev, with the review
 * of exactly its bundle: under the landing lock it fetches the bundle, checks
 * it holds the record's head on top of the dev it was checked against,
 * fast-forwards dev, records the review and pushes the mirrors. It runs Git
 * alone, with no hook, and nothing from the bundle; `dir` stays for the
 * caller. Resolves the exit code.
 * @param {string} cwd
 * @param {Deps} deps
 * @param {string | undefined} dir
 * @param {string | undefined} reviewFile
 */
export async function finishHandOff(cwd, deps, dir, reviewFile) {
  const { log } = deps;
  if (onWindows(log)) return 1;
  if (!dir || !reviewFile) {
    log(
      `Finish with --finish <dir> --review <file.json>: the hand-off's directory and the independent review of its bundle, ${reviewShape}.`,
    );
    return 1;
  }
  let handoff;
  let review;
  try {
    let text;
    try {
      text = fs.readFileSync(path.join(dir, handoffRecord), "utf8");
    } catch (error) {
      throw new Error(`${dir} holds no hand-off: ${reason(error)}.`);
    }
    handoff = readHandoff(text);
    review = readReview(fs.readFileSync(reviewFile, "utf8"));
  } catch (error) {
    log(`${reason(error)} Nothing landed.`);
    return 1;
  }
  // The reviewer reviewed exactly the bundle, so nothing lands after it.
  if (review.head.toLowerCase() !== handoff.head) {
    log(
      `The review record's head ${review.head} is not the hand-off's head ${handoff.head}; nothing landed.`,
    );
    return 1;
  }
  review = { ...review, head: handoff.head };
  const here = sealedGit(cwd);
  const top = here(["rev-parse", "--show-toplevel"]).stdout.trim();
  if (!top) {
    log(`Finish from the main checkout; ${cwd} is not in a Git repository.`);
    return 1;
  }
  const common = path.resolve(
    top,
    here(["rev-parse", "--git-common-dir"]).stdout.trim(),
  );
  const main = path.dirname(common);
  const git = sealedGit(main);
  if (git(["check-ref-format", `refs/heads/${handoff.branch}`]).status !== 0) {
    log(`The hand-off's branch ${handoff.branch} is not a valid branch name.`);
    return 1;
  }
  // A landing waiting for the user's DazedTL holds the lock, so this answers
  // before waiting for it.
  if (appRunning(main, deps.processes())) {
    log(appOpenLine(main));
    return appOpen;
  }
  await warnRedDev(deps, main);
  const time = timer(deps.now);
  return lockedRun(
    deps,
    git,
    { branch: handoff.branch, worktree: path.resolve(dir) },
    time,
    () =>
      finishUnderLock(
        deps,
        {
          main,
          common,
          bundle: path.resolve(dir, handoffBundle),
          handoff,
          review,
        },
        time,
      ),
    lockLimit,
  );
}

/**
 * --finish while this session holds the lock.
 * @param {Deps} deps
 * @param {{ main: string, common: string, bundle: string, handoff: ReturnType<typeof readHandoff>, review: ReturnType<typeof readReview> }} where
 * @param {ReturnType<typeof timer>} time
 * @returns {Promise<Outcome>}
 */
async function finishUnderLock(
  deps,
  { main, common, bundle, handoff, review },
  time,
) {
  const { branch, head, base } = handoff;
  const git = sealedGit(main);
  const out = (/** @type {string[]} */ ...args) => git(args).stdout.trim();
  time.lap("lock wait");
  const verified = git(["bundle", "verify", "--quiet", bundle]);
  if (verified.status !== 0)
    return outcome(
      1,
      tail(verified.stdout + verified.stderr),
      "The hand-off's bundle does not verify against this repository; nothing landed.",
    );
  try {
    const fetched = git([
      "-c",
      "fetch.fsckObjects=true",
      "fetch",
      "--quiet",
      "--no-tags",
      "--no-write-fetch-head",
      bundle,
      `+refs/heads/${branch}:${handoffRef}`,
    ]);
    if (fetched.status !== 0)
      return outcome(
        1,
        tail(fetched.stdout + fetched.stderr),
        `Fetching ${branch} from the hand-off's bundle failed; nothing landed.`,
      );
    const fetchedHead = out("rev-parse", "--verify", `${handoffRef}^{commit}`);
    if (fetchedHead !== head)
      return outcome(
        1,
        `The hand-off's bundle holds ${fetchedHead.slice(0, 7)} for ${branch}, not the head ${head.slice(0, 7)} its record names; nothing landed.`,
      );
    if (
      head === base ||
      git(["merge-base", "--is-ancestor", base, head]).status !== 0
    )
      return outcome(
        1,
        `The hand-off's head ${head.slice(0, 7)} does not build on its base ${base.slice(0, 7)}; nothing landed.`,
      );
    time.lap("verify");
    const dev = out("rev-parse", "--verify", "refs/heads/dev");
    if (dev !== base)
      return outcome(
        devMoved,
        `dev moved since the hand-off's checks (from ${base.slice(0, 7)} to ${dev.slice(0, 7)}); merge dev into ${branch} and hand off again.`,
      );
    if (appRunning(main, deps.processes()))
      return outcome(appOpen, appOpenLine(main));
    const targets = mirrorTargets(git, main);
    const refused = moveDev(git, main, head);
    // Only a busy main checkout clears by itself; a retry would hit
    // anything else again.
    if (refused?.cause === "busy")
      return outcome(
        mainBusy,
        ...refused.report,
        "The main checkout can't take it now; nothing changed; finish again later.",
      );
    if (refused?.cause === "moved")
      return outcome(
        devMoved,
        ...refused.report.slice(0, -1),
        `dev moved since the hand-off's checks; merge dev into ${branch} and hand off again.`,
      );
    if (refused) return outcome(1, ...refused.report);
    recordReview(deps, common, { branch, range: `${base}..${head}`, review });
    const unpushed = await pushDev(deps, main, targets, sealed);
    time.lap("push");
    return landed(git, base, head, unpushed);
  } finally {
    git(["update-ref", "-d", handoffRef]);
  }
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
  const usage = [
    "Usage: node scripts/land.mjs --review <file.json>",
    "       node scripts/land.mjs --hand-off <dir>",
    "       node scripts/land.mjs --finish <dir> --review <file.json>",
  ].join("\n");
  /** @type {{ review?: string, "hand-off"?: string, finish?: string }} */
  let values = {};
  try {
    ({ values } = parseArgs({
      options: {
        review: { type: "string" },
        "hand-off": { type: "string" },
        finish: { type: "string" },
      },
    }));
  } catch {
    console.error(usage);
    process.exit(1);
  }
  const { review, "hand-off": handOffDir, finish } = values;
  if (finish !== undefined && handOffDir === undefined)
    process.exitCode = await finishHandOff(
      process.cwd(),
      realDeps(),
      finish,
      review,
    );
  else if (handOffDir !== undefined && finish === undefined) {
    // The intake reviews what a worker hands off.
    if (review !== undefined) {
      console.error(
        `--hand-off takes no --review: the intake reviews the hand-off.\n${usage}`,
      );
      process.exit(1);
    }
    process.exitCode = await handOff(process.cwd(), realDeps(), handOffDir);
  } else if (handOffDir === undefined && finish === undefined)
    process.exitCode = await land(process.cwd(), realDeps(), review);
  else {
    console.error(usage);
    process.exit(1);
  }
}
