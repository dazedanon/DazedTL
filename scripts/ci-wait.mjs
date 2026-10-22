// Waits for the CI run of a commit on GitHub without spending the API limit
// that every parallel session shares: conditional requests (a 304 is free),
// one status check every 30 s, and a sleep until the reset when few calls
// are left. Usage: node scripts/ci-wait.mjs <sha> [--branch <b>] [--repo <o/r>]
// Exits 0 when the run succeeds and 1 when it fails, is cancelled for good
// or never appears.
import { execFileSync } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { pathToFileURL } from "node:url";

export const defaultRepository = "dazedanon/DazedTL";
export const workflow = ".github/workflows/ci.yml";
const lowCalls = 50;

/** A GitHub API reader that sends If-None-Match and pauses near the limit. */
export function githubReader({
  token,
  fetchImpl = fetch,
  wait = sleep,
  now = Date.now,
  log = () => {},
}) {
  const cache = new Map();
  return async function read(route) {
    const url = `https://api.github.com/${route}`;
    const known = cache.get(route);
    for (;;) {
      const response = await fetchImpl(url, {
        headers: {
          Accept: "application/vnd.github+json",
          "User-Agent": "DazedTL ci-wait",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(known ? { "If-None-Match": known.etag } : {}),
        },
        signal: AbortSignal.timeout(30_000),
      });
      const left = response.headers.get("x-ratelimit-remaining");
      const resetAt = Number(response.headers.get("x-ratelimit-reset")) * 1000;
      const limited =
        (response.status === 403 || response.status === 429) && left === "0";
      // A 304 costs nothing, so only a counted answer can run the limit down.
      if (
        limited ||
        (response.status !== 304 && left !== null && Number(left) < lowCalls)
      ) {
        const pause = Math.max(0, resetAt - now()) + 2000;
        log(
          `GitHub API calls are nearly spent; sleeping ${Math.ceil(pause / 60000)} min until the reset.`,
        );
        await wait(pause);
        if (limited) continue;
      }
      if (response.status === 304 && known) return known.body;
      if (response.status === 404) return null;
      if (!response.ok)
        throw new Error(`GitHub answered ${response.status} for ${route}.`);
      const body = await response.json();
      const etag = response.headers.get("etag");
      if (etag) cache.set(route, { etag, body });
      return body;
    }
  };
}

/** Asks GitHub to do something, such as rerun a run's failed jobs. */
export function githubWriter({ token, fetchImpl = fetch }) {
  return async function post(route) {
    const response = await fetchImpl(`https://api.github.com/${route}`, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "DazedTL ci-wait",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: AbortSignal.timeout(30_000),
    });
    if (!response.ok)
      throw new Error(`GitHub answered ${response.status} for ${route}.`);
  };
}

/** Whether a finished run failed, rather than passed or was cancelled. */
export const failedRun = (run) =>
  ["failure", "timed_out", "startup_failure"].includes(run?.conclusion);

/**
 * Whether a run failed on its first attempt. It gets one rerun of its failed
 * jobs, since most first failures are Windows flakes; a second is real.
 */
export const firstFailure = (run) =>
  failedRun(run) && (run.run_attempt ?? 1) === 1;

/** The names of a finished run's jobs that did not pass. */
export async function failedJobs(read, repository, run) {
  const jobs = await read(
    `repos/${repository}/actions/runs/${run.id}/jobs?per_page=100`,
  );
  return (jobs?.jobs || [])
    .filter((job) => !["success", "skipped"].includes(job.conclusion))
    .map((job) => job.name);
}

/**
 * Waits for the CI run of `sha`, following a newer run on the same branch
 * when a later push supersedes it. Resolves `{ ok, run, failed }`. After a
 * rerun, `attempt` names the attempt to wait for, since GitHub can still
 * answer with the earlier attempt's result for a moment.
 */
export async function waitForCI({
  sha,
  branch,
  repository = defaultRepository,
  read,
  wait = sleep,
  now = Date.now,
  interval = 30_000,
  startTimeout = 5 * 60_000,
  timeout = 90 * 60_000,
  attempt = 1,
  log = () => {},
}) {
  const started = now();
  const done = (item) =>
    item?.status === "completed" && (item.run_attempt ?? 1) >= attempt;
  let run = null;
  let shown = "";
  for (;;) {
    if (!done(run)) {
      const found = await read(
        run
          ? `repos/${repository}/actions/runs/${run.id}`
          : `repos/${repository}/actions/runs?head_sha=${sha}&per_page=50`,
      );
      if (run) run = found || run;
      else
        run =
          (found?.workflow_runs || [])
            .filter((item) => item.path === workflow)
            .sort(
              (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
            )[0] || null;
    }
    if (done(run)) {
      if (run.conclusion === "cancelled") {
        const where = branch || run.head_branch;
        const found = await read(
          `repos/${repository}/actions/runs?branch=${encodeURIComponent(where)}&per_page=20`,
        );
        const newer = (found?.workflow_runs || [])
          .filter(
            (item) =>
              item.path === workflow &&
              Date.parse(item.created_at) > Date.parse(run.created_at),
          )
          .sort(
            (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
          )[0];
        if (newer) {
          log(
            `Run ${run.id} was superseded; following ${newer.id} (${newer.head_sha.slice(0, 7)}).`,
          );
          run = newer;
          continue;
        }
      }
      if (run.conclusion === "success") return { ok: true, run, failed: [] };
      return {
        ok: false,
        run,
        failed: await failedJobs(read, repository, run),
      };
    }
    const elapsed = now() - started;
    if (!run && elapsed > startTimeout)
      return {
        ok: false,
        run: null,
        failed: [],
        reason: `CI did not start for ${sha.slice(0, 7)}.`,
      };
    if (elapsed > timeout)
      return {
        ok: false,
        run,
        failed: [],
        reason: `CI did not finish within ${timeout / 60000} minutes.`,
      };
    const status = run
      ? `${run.status.replace("_", " ")}: ${run.html_url}`
      : "waiting to start";
    if (status !== shown) log(`CI for ${sha.slice(0, 7)} is ${status}`);
    shown = status;
    await wait(interval);
  }
}

export function ghToken() {
  if (process.env.GH_TOKEN || process.env.GITHUB_TOKEN)
    return process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
  try {
    return execFileSync("gh", ["auth", "token"], { encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

async function main() {
  const args = process.argv.slice(2);
  const option = (name) => {
    const at = args.indexOf(name);
    return at < 0 ? undefined : args.splice(at, 2)[1];
  };
  const branch = option("--branch");
  const repository = option("--repo") || defaultRepository;
  const sha = args[0];
  if (!sha || !/^[0-9a-f]{7,40}$/.test(sha)) {
    console.error(
      "Usage: node scripts/ci-wait.mjs <sha> [--branch <b>] [--repo <owner/repo>]",
    );
    process.exit(2);
  }
  const log = (message) => console.log(message);
  const read = githubReader({ token: ghToken(), log });
  const full =
    sha.length === 40
      ? sha
      : (await read(`repos/${repository}/commits/${sha}`))?.sha;
  if (!full) {
    console.error(`GitHub does not have commit ${sha}; push it first.`);
    process.exit(1);
  }
  const result = await waitForCI({ sha: full, branch, repository, read, log });
  if (result.ok) {
    console.log(`CI passed for ${full.slice(0, 7)}: ${result.run.html_url}`);
    return;
  }
  if (!result.run) {
    console.error(result.reason);
  } else {
    console.error(
      `CI ${result.run.conclusion || "did not finish"} for ${result.run.head_sha.slice(0, 7)}: ${result.run.html_url}`,
    );
    if (result.failed.length)
      console.error(`Failed jobs: ${result.failed.join(", ")}`);
    if (result.reason) console.error(result.reason);
    console.error(
      `Read the log: gh run view ${result.run.id} --repo ${repository} --log-failed`,
    );
  }
  process.exit(1);
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) await main();
