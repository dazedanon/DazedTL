// Keeps DazedTL's mirrors to the branches they are for: dev, main, the CI
// branches land.mjs pushes and deletes (land/<branch>) and scratch branches
// for a Windows run (run/<name>). Sessions once pushed their working branches
// to the mirrors and left them there by the dozen, so two checks share this
// rule: the pre-push hook in scripts/hooks, which setup.mjs installs, refuses
// any other branch pushed to a mirror, and land.mjs, after pushing dev to a
// mirror, deletes there each run/ branch a week old and each other branch dev
// already has. See "Branches and releases" in docs/development.md.
//
//   node scripts/branches.mjs pre-push <remote> <url>
//
// is the hook's check: it reads Git's lines for the refs being pushed on
// stdin and exits 1, saying why, when the push is refused.
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { repository } from "./release.mjs";
import { mirrors } from "./update.mjs";

/** How old a run/ branch's newest commit gets before a landing deletes it. */
export const scratchAge = 7 * 24 * 60 * 60_000;
/** Where setup points Git for its hooks, relative to each worktree. */
const hooksPath = "scripts/hooks";
const networkTimeout = 2 * 60_000;

/** Whether the mirrors are for `branch`. */
const mirrorBranch = (/** @type {string} */ branch) =>
  branch === "dev" || branch === "main" || /^(land|run)\/./.test(branch);

const lines = (/** @type {string} */ text) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
const tail = (/** @type {string} */ text) => lines(text).slice(-5).join("\n");

/**
 * Why Git must not push `updates` to `url`, or null when it may. `updates`
 * holds the lines Git gives a pre-push hook, "<local ref> <local hash>
 * <remote ref> <remote hash>". Only a branch the mirrors are not for, pushed
 * to a mirror that `folder`'s release/mirrors.json names, is refused; deleting
 * a branch, tags and any push elsewhere, such as to a fork, pass.
 * @param {string} url
 * @param {string} updates
 * @param {string} folder
 */
export function refusal(url, updates, folder) {
  const site = repository(url);
  /** @type {{ url: string }[]} */
  let list;
  try {
    list = mirrors(folder);
  } catch {
    return null;
  }
  if (!site || !list.some((mirror) => repository(mirror.url) === site))
    return null;
  const refused = lines(updates).flatMap((line) => {
    const [, local = "", remote = ""] = line.split(/\s+/);
    if (!remote.startsWith("refs/heads/") || /^0+$/.test(local)) return [];
    const branch = remote.slice("refs/heads/".length);
    return mirrorBranch(branch) ? [] : [branch];
  });
  if (!refused.length) return null;
  return [
    `Refused to push ${refused.join(", ")} to ${url}: DazedTL's mirrors hold only dev, main, land.mjs's land/ branches and run/ scratch branches.`,
    "Land a finished branch with node scripts/land.mjs, as the dazedtl-land skill says: it pushes dev and runs the CI the branch needs.",
    'For a Windows run, push the branch to GitHub as run/<name> and delete it after the run, as "CI" in docs/development.md says.',
  ].join("\n");
}

/**
 * Points the Git checkout at `folder` at the hooks in scripts/hooks, so its
 * pre-push hook guards the mirrors. Leaves Git alone outside a checkout of
 * its own, such as a release ZIP, and where the user set core.hooksPath
 * elsewhere or keeps hooks of their own; it then returns a line saying the
 * guard is off and how to keep it.
 * @param {string} folder
 * @returns {string | null}
 */
export function installHooks(folder) {
  const git = (/** @type {string[]} */ ...args) =>
    spawnSync("git", args, {
      cwd: folder,
      encoding: "utf8",
      windowsHide: true,
    });
  const real = (/** @type {string} */ place) => fs.realpathSync.native(place);
  const top = git("rev-parse", "--show-toplevel");
  // A folder inside some other repository, such as a home folder kept in Git.
  if (top.status !== 0 || real(top.stdout.trim()) !== real(folder)) return null;
  const set = git("config", "--get", "core.hooksPath").stdout.trim();
  const common = path.resolve(
    folder,
    git("rev-parse", "--git-common-dir").stdout.trim(),
  );
  // These hooks, by a relative path or the absolute one of this checkout or
  // of the main checkout that its worktrees share.
  const ours = [folder, path.dirname(common)].map((checkout) =>
    path.join(real(checkout), hooksPath),
  );
  if (set && ours.includes(path.resolve(real(folder), set))) return null;
  const own = path.join(common, "hooks");
  const active = fs.existsSync(own)
    ? fs.readdirSync(own).filter((name) => !name.endsWith(".sample"))
    : [];
  if (set || active.length)
    return `Git runs the hooks in ${set || own}, so DazedTL's push guard is off; to keep it, run ${hooksPath}/pre-push from your own pre-push hook with the same arguments and input.`;
  git("config", "core.hooksPath", hooksPath);
  return null;
}

/**
 * @typedef {{
 *   run: (cwd: string, command: string, args: string[], timeout?: number) => Promise<{ status: number, output: string }>,
 *   log: (line: string) => void,
 *   now?: () => number,
 * }} PruneDeps
 */

/**
 * Deletes from the mirror `target` each run/ branch whose newest commit is
 * older than scratchAge, since a Windows run may use a younger one, and each
 * other branch but dev and main whose commits the dev of the checkout at
 * `main` already has, then logs any other branch it holds that dev lacks. Run right after pushing dev there. Git runs with `options`
 * before each command. Never throws: a mirror it cannot read or change is
 * logged and left.
 * @param {PruneDeps} deps
 * @param {string} main
 * @param {{ name: string, url: string }} target
 * @param {string[]} [options]
 */
export async function prune(
  { run, log, now = Date.now },
  main,
  target,
  options = [],
) {
  const git = (/** @type {string[]} */ args) =>
    run(main, "git", [...options, ...args], networkTimeout);
  const listed = await git(["ls-remote", "--heads", target.url]);
  if (listed.status !== 0) {
    log(
      `Could not list the branches on ${target.name}, so none were cleaned up there:\n${tail(listed.output)}`,
    );
    return;
  }
  const heads = lines(listed.output).flatMap((line) => {
    const found = /^([0-9a-f]{40,64})\s+refs\/heads\/(\S+)$/.exec(line);
    return found && found[2] !== "dev" && found[2] !== "main"
      ? [{ tip: found[1], branch: found[2] }]
      : [];
  });
  if (!heads.length) return;
  const known = async (/** @type {string} */ tip) =>
    (await git(["cat-file", "-e", `${tip}^{commit}`])).status === 0;
  /** @type {string[]} */
  const fetch = [];
  for (const { tip, branch } of heads)
    if (!(await known(tip))) fetch.push(`refs/heads/${branch}`);
  // A branch pushed from another machine; its commits come along to judge it.
  if (fetch.length)
    await git([
      "fetch",
      "--quiet",
      "--no-tags",
      "--no-write-fetch-head",
      target.url,
      ...fetch,
    ]);
  /**
   * Whether dev has each of the commits at `tip`: merged, or picked one by
   * one from a branch with no merge of its own, since git cherry passes over
   * merges and whatever was resolved or added in them.
   */
  const inDev = async (/** @type {string} */ tip) => {
    if ((await git(["merge-base", "--is-ancestor", tip, "dev"])).status === 0)
      return true;
    const merges = await git(["rev-list", "--merges", `dev..${tip}`]);
    if (merges.status !== 0 || merges.output.trim()) return false;
    const picked = await git(["cherry", "dev", tip]);
    return picked.status === 0 && !/^\+/m.test(picked.output);
  };
  const stale = async (/** @type {string} */ tip) => {
    const made = await git(["log", "-1", "--format=%ct", tip]);
    const seconds = Number(made.output.trim());
    return made.status === 0 && now() - seconds * 1000 > scratchAge;
  };
  /** @type {string[]} */
  const drop = [];
  /** @type {string[]} */
  const left = [];
  for (const { tip, branch } of heads) {
    if (!(await known(tip))) {
      if (!mirrorBranch(branch)) left.push(branch);
    } else if (branch.startsWith("run/")) {
      if (await stale(tip)) drop.push(branch);
    } else if (await inDev(tip)) drop.push(branch);
    else if (!mirrorBranch(branch)) left.push(branch);
  }
  // One branch a push, so a refused one names only itself.
  /** @type {string[]} */
  const dropped = [];
  for (const branch of drop) {
    const deleted = await git([
      "push",
      "--quiet",
      target.url,
      "--delete",
      `refs/heads/${branch}`,
    ]);
    if (deleted.status === 0) dropped.push(branch);
    else
      log(
        `Could not delete ${branch} from ${target.name}:\n${tail(deleted.output)}`,
      );
  }
  if (dropped.length)
    log(
      `Deleted from ${target.name} the branches dev has or a Windows run left: ${dropped.join(", ")}.`,
    );
  if (left.length)
    log(
      `${target.name} also holds ${left.join(", ")}, which dev lacks; delete each there once nothing needs it.`,
    );
}

if (import.meta.main) {
  const [command, , url] = process.argv.slice(2);
  if (command !== "pre-push" || !url) {
    console.error("Usage: node scripts/branches.mjs pre-push <remote> <url>");
    process.exit(2);
  }
  // Git runs a hook from the top of the worktree being pushed.
  const why = refusal(url, fs.readFileSync(0, "utf8"), process.cwd());
  if (why) {
    console.error(why);
    process.exit(1);
  }
}
