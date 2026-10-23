// The lock that lets one landing or release at a time move dev: the ref
// refs/dazedtl/land-lock in the shared repository, pointing to a blob that
// names its holder. Git's compare-and-swap ref updates take, take over and
// release it, so two sessions can never both hold it. A holder renews it
// while it works; a lock whose process has gone, or that nobody renewed for
// 20 minutes, may be taken over.
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";

export const lockRef = "refs/dazedtl/land-lock";
const lockAge = 20 * 60_000;
const renewEvery = 5 * 60_000;
const lockPoll = 3000;
// Longer than a landing takes, so only a wait on something slower, such as a
// holder waiting for the user, is worth telling them about.
const lockNotice = 5 * 60_000;

/**
 * @typedef {(args: string[], input?: string) => { status: number, stdout: string, stderr: string }} Git
 * @typedef {{ pid: number, pidNamespace: string | null, branch: string, worktree: string, started: string }} Holder
 * @typedef {{ blob: string, holder: Holder }} Lock
 */

/** Runs Git in `cwd`. @returns {Git} */
export function gitIn(/** @type {string} */ cwd) {
  return (args, input) => {
    const result = spawnSync("git", args, { cwd, input, encoding: "utf8" });
    return {
      status: result.status ?? 1,
      stdout: result.stdout ?? "",
      stderr: result.stderr || result.error?.message || "",
    };
  };
}

/** This process's PID namespace, so a sandboxed holder's PID is not misread. */
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

/**
 * Whether a holder has gone or went 20 minutes without renewing the lock. A
 * holder in another PID namespace, such as another sandbox, is judged by age.
 * @param {Holder | null} holder
 * @param {{ now: () => number, alive: (pid: number) => boolean, namespace: string | null }} context
 */
export function staleHolder(holder, { now, alive, namespace }) {
  if (!holder || typeof holder.pid !== "number") return true;
  if (!(now() - Date.parse(holder.started) < lockAge)) return true;
  return holder.pidNamespace === namespace && !alive(holder.pid);
}

/** The lock's current blob and holder, or null when nobody holds it. */
function current(/** @type {Git} */ git) {
  const blob = git(["rev-parse", "-q", "--verify", lockRef]).stdout.trim();
  if (!blob) return null;
  /** @type {Holder | null} */
  let holder = null;
  try {
    holder = JSON.parse(git(["cat-file", "blob", blob]).stdout);
  } catch {
    // Unreadable, so stale.
  }
  return { blob, holder };
}

/** Writes `holder`, stamped now, as a blob. @returns {Lock} */
function stamp(
  /** @type {Git} */ git,
  /** @type {Omit<Holder, "started">} */ who,
  /** @type {() => number} */ now,
) {
  const holder = { ...who, started: new Date(now()).toISOString() };
  const written = git(
    ["hash-object", "-w", "--stdin"],
    `${JSON.stringify(holder)}\n`,
  );
  if (written.status !== 0) throw new Error(written.stderr.trim());
  return { blob: written.stdout.trim(), holder };
}

/**
 * Takes the lock for `who`, waiting while a live holder has it and taking
 * over a stale one. A wait past 5 minutes goes to `notify` once, and so does
 * its end, so the user hears of it while the waiter runs in the background.
 * @param {Git} git
 * @param {{ branch: string, worktree: string, pid?: number }} who
 * @param {{ now?: () => number, alive?: (pid: number) => boolean, namespace?: string | null, wait?: (ms: number) => Promise<unknown>, log?: (line: string) => void, notify?: (line: string) => void }} [options]
 * @returns {Promise<Lock>}
 */
export async function acquireLock(
  git,
  who,
  {
    now = Date.now,
    alive = processAlive,
    namespace = pidNamespace(),
    wait = sleep,
    log = () => {},
    notify = log,
  } = {},
) {
  const self = { pid: process.pid, pidNamespace: namespace, ...who };
  const since = now();
  const minutes = () => `${Math.round((now() - since) / 60_000)} min`;
  let shown = "";
  let noticed = false;
  for (;;) {
    const held = current(git);
    if (!held) {
      const lock = stamp(git, self, now);
      if (git(["update-ref", lockRef, lock.blob, ""]).status === 0) {
        if (noticed) notify(`Got the landing lock after ${minutes()}.`);
        return lock;
      }
      continue;
    }
    if (staleHolder(held.holder, { now, alive, namespace })) {
      const lock = stamp(git, self, now);
      if (git(["update-ref", lockRef, lock.blob, held.blob]).status === 0) {
        (noticed ? notify : log)(
          `Took over the landing lock from ${held.holder ? `${held.holder.branch} (pid ${held.holder.pid})` : "an unreadable holder"}, which had gone or not renewed it for ${lockAge / 60_000} min.`,
        );
        return lock;
      }
      continue;
    }
    const name = `${held.holder?.branch} (pid ${held.holder?.pid})`;
    if (name !== shown) log(`Waiting for the landing lock, held by ${name}.`);
    shown = name;
    if (!noticed && now() - since >= lockNotice) {
      notify(
        `Still waiting for the landing lock after ${minutes()}, held by ${name}.`,
      );
      noticed = true;
    }
    await wait(lockPoll);
  }
}

/** Stamps a held lock again. Resolves false when another session took it. */
export function renewLock(
  /** @type {Git} */ git,
  /** @type {Lock} */ lock,
  now = Date.now,
) {
  const { pid, pidNamespace, branch, worktree } = lock.holder;
  const next = stamp(git, { pid, pidNamespace, branch, worktree }, now);
  if (git(["update-ref", lockRef, next.blob, lock.blob]).status !== 0)
    return false;
  Object.assign(lock, next);
  return true;
}

/** Removes the lock if `lock` still holds it. */
export function releaseLock(/** @type {Git} */ git, /** @type {Lock} */ lock) {
  return git(["update-ref", "-d", lockRef, lock.blob]).status === 0;
}

/**
 * Runs `task` holding the lock, renewing it every 5 minutes and releasing it
 * when the task ends, the process exits or a signal stops it; `onStop` runs
 * first on a signal, to stop child processes.
 * @template T
 * @param {Git} git
 * @param {{ branch: string, worktree: string }} who
 * @param {() => Promise<T>} task
 * @param {{ log?: (line: string) => void, notify?: (line: string) => void, onStop?: () => void }} [options]
 * @returns {Promise<T>}
 */
export async function withLock(
  git,
  who,
  task,
  { log = () => {}, notify = log, onStop } = {},
) {
  const lock = await acquireLock(git, who, { log, notify });
  let lost = false;
  const renew = setInterval(() => {
    if (!lost && !renewLock(git, lock)) {
      lost = true;
      log("Another session took over the landing lock.");
    }
  }, renewEvery);
  renew.unref();
  const release = () => releaseLock(git, lock);
  const stop = (/** @type {number} */ code) => () => {
    onStop?.();
    release();
    process.exit(code);
  };
  const interrupt = stop(130);
  const terminate = stop(143);
  process.on("exit", release);
  process.on("SIGINT", interrupt);
  process.on("SIGTERM", terminate);
  try {
    return await task();
  } finally {
    clearInterval(renew);
    process.off("exit", release);
    process.off("SIGINT", interrupt);
    process.off("SIGTERM", terminate);
    release();
  }
}
