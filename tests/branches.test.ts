import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import {
  installHooks,
  prune,
  refusal,
  scratchAge,
} from "../scripts/branches.mjs";
import { gitIn } from "../scripts/land-lock.mjs";

const hooks = path.join(import.meta.dirname, "..", "scripts", "hooks");
const zero = "0".repeat(40);
const tip = "a".repeat(40);
const windows = process.platform === "win32";

const temp = (t: { after: (fn: () => void) => void }) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-branches-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
};
const writeMirrors = (folder: string, urls: string[]) => {
  fs.mkdirSync(path.join(folder, "release"), { recursive: true });
  fs.writeFileSync(
    path.join(folder, "release", "mirrors.json"),
    JSON.stringify(urls.map((url, i) => ({ name: `M${i}`, type: "x", url }))),
  );
};
const pushing = (branch: string) =>
  `refs/heads/${branch} ${tip} refs/heads/${branch} ${zero}`;
const repo = (dir: string) => {
  const git = gitIn(dir);
  git(["init", "-q", "-b", "dev"]);
  git(["config", "user.name", "Test"]);
  git(["config", "user.email", "test@example.com"]);
  git(["config", "commit.gpgsign", "false"]);
  return git;
};

test("the push guard refuses only a branch the mirrors are not for, pushed to a mirror", (t) => {
  const dir = temp(t);
  writeMirrors(dir, [
    "https://github.com/dazedanon/DazedTL",
    "https://gitgud.io/DazedAnon/DazedTL",
  ]);
  const github = "git@github.com:dazedanon/DazedTL.git";
  const why = refusal(github, pushing("claude/x"), dir) ?? "";
  assert.match(why, /^Refused to push claude\/x to git@github\.com/);
  assert.match(why, /node scripts\/land\.mjs/);
  assert.match(why, /run\/<name>/);
  // Both spellings of each mirror count.
  for (const url of [
    "https://github.com/dazedanon/DazedTL",
    "git@ssh.gitgud.io:DazedAnon/dazedtl.git",
  ])
    assert.ok(refusal(url, pushing("worktree-agent-1"), dir), url);
  // Only the stray branch of a push is named.
  assert.match(
    refusal(github, `${pushing("dev")}\n${pushing("fix/y")}\n`, dir) ?? "",
    /^Refused to push fix\/y to/,
  );
  for (const allowed of [
    pushing("dev"),
    pushing("main"),
    pushing("land/claude/x"),
    pushing("run/windows-check"),
    `refs/tags/v2.0.0 ${tip} refs/tags/v2.0.0 ${zero}`,
    `(delete) ${zero} refs/heads/claude/x ${tip}`,
    "",
  ])
    assert.equal(refusal(github, allowed, dir), null, allowed);
  // A fork, another site, or a checkout without the mirrors list.
  assert.equal(
    refusal("git@github.com:someone/DazedTL.git", pushing("x"), dir),
    null,
  );
  assert.equal(refusal("/tmp/elsewhere.git", pushing("x"), dir), null);
  assert.equal(refusal(github, pushing("x"), os.tmpdir()), null);
});

test("Git runs the guard on a real push, which refuses a stray branch and lets the mirrors' own through", (t) => {
  const dir = temp(t);
  const bare = path.join(dir, "mirror.git");
  const work = path.join(dir, "work");
  gitIn(dir)(["init", "-q", "--bare", bare]);
  fs.mkdirSync(work);
  const git = repo(work);
  const url = pathToFileURL(bare).href;
  writeMirrors(work, [url]);
  git(["add", "-A"]);
  git(["commit", "-qm", "mirrors"]);
  git(["config", "core.hooksPath", hooks]);
  const push = (...args: string[]) => git(["push", "-q", url, ...args]);
  const heads = () => gitIn(bare)(["for-each-ref", "--format=%(refname)"]);

  const refused = push("HEAD:refs/heads/claude/x");
  assert.notEqual(refused.status, 0);
  assert.match(refused.stderr, /Refused to push claude\/x/);
  assert.equal(heads().stdout, "");
  for (const branch of ["dev", "land/claude/x", "run/check"])
    assert.equal(push(`HEAD:refs/heads/${branch}`).status, 0, branch);
  assert.equal(push("--delete", "refs/heads/run/check").status, 0);
  assert.equal(heads().stdout, "refs/heads/dev\nrefs/heads/land/claude/x\n");
  // Any other remote takes any branch.
  const fork = path.join(dir, "fork.git");
  gitIn(dir)(["init", "-q", "--bare", fork]);
  assert.equal(
    git(["push", "-q", pathToFileURL(fork).href, "HEAD:refs/heads/x"]).status,
    0,
  );
});

test(
  "the hook passes when its script or Node is missing",
  { skip: windows },
  (t) => {
    const dir = temp(t);
    const lone = path.join(dir, "hooks", "pre-push");
    fs.mkdirSync(path.dirname(lone));
    fs.copyFileSync(path.join(hooks, "pre-push"), lone);
    const run = (hook: string, env: NodeJS.ProcessEnv = process.env) =>
      spawnSync(
        "/bin/sh",
        [hook, "origin", "git@github.com:dazedanon/DazedTL.git"],
        {
          cwd: dir,
          env,
          input: pushing("claude/x"),
          encoding: "utf8",
        },
      );
    // A worktree from before the script.
    assert.equal(run(lone).status, 0);
    // Node not on PATH: only what the shim needs besides it.
    const bin = path.join(dir, "bin");
    fs.mkdirSync(bin);
    for (const tool of ["dirname", "cat"]) {
      const found = spawnSync("/bin/sh", ["-c", `command -v ${tool}`], {
        encoding: "utf8",
      }).stdout.trim();
      fs.symlinkSync(found, path.join(bin, tool));
    }
    writeMirrors(dir, ["https://github.com/dazedanon/DazedTL"]);
    const real = path.join(hooks, "pre-push");
    assert.equal(run(real, { PATH: bin }).status, 0);
    // With Node, the same push is refused.
    assert.equal(run(real).status, 1);
  },
);

test("setup points a development checkout at the tracked hooks, and leaves the user's own hooks alone", (t) => {
  const dir = temp(t);
  const hooksPath = (folder: string) =>
    gitIn(folder)(["config", "--get", "core.hooksPath"]).stdout.trim();

  // A release ZIP is no Git checkout.
  const unpacked = path.join(dir, "zip");
  fs.mkdirSync(unpacked);
  assert.equal(installHooks(unpacked), null);

  const fresh = path.join(dir, "fresh");
  fs.mkdirSync(fresh);
  repo(fresh);
  assert.equal(installHooks(fresh), null);
  assert.equal(hooksPath(fresh), "scripts/hooks");
  assert.equal(installHooks(fresh), null);

  // DazedTL unpacked inside some other repository, such as a home folder.
  const inner = path.join(fresh, "DazedTL");
  fs.mkdirSync(inner);
  gitIn(fresh)(["config", "--unset", "core.hooksPath"]);
  assert.equal(installHooks(inner), null);
  assert.equal(hooksPath(fresh), "");

  const chosen = path.join(dir, "chosen");
  fs.mkdirSync(chosen);
  repo(chosen)(["config", "core.hooksPath", ".githooks"]);
  assert.match(
    installHooks(chosen) ?? "",
    /hooks in \.githooks, so DazedTL's push guard in scripts\/hooks is off/,
  );
  assert.equal(hooksPath(chosen), ".githooks");

  const own = path.join(dir, "own");
  fs.mkdirSync(own);
  repo(own);
  fs.writeFileSync(
    path.join(own, ".git", "hooks", "pre-commit"),
    "#!/bin/sh\n",
  );
  assert.match(installHooks(own) ?? "", /push guard in scripts\/hooks is off/);
  assert.equal(hooksPath(own), "");
});

test("a landing deletes from a mirror the branches dev has and stale run/ branches, and names the rest", async (t) => {
  const dir = temp(t);
  const main = path.join(dir, "main");
  const other = path.join(dir, "other");
  const bare = path.join(dir, "mirror.git");
  fs.mkdirSync(main);
  const git = repo(main);
  gitIn(dir)(["init", "-q", "--bare", bare]);
  const commit = (top: string, file: string, date?: string) => {
    fs.writeFileSync(path.join(top, file), `${file}\n`);
    spawnSync("git", ["add", file], { cwd: top });
    spawnSync("git", ["commit", "-qm", file], {
      cwd: top,
      env: date ? { ...process.env, GIT_COMMITTER_DATE: date } : process.env,
    });
    return gitIn(top)(["rev-parse", "HEAD"]).stdout.trim();
  };
  const toMirror = (top: string, ref: string, branch: string) =>
    assert.equal(
      gitIn(top)(["push", "-q", bare, `${ref}:refs/heads/${branch}`]).status,
      0,
    );
  const base = commit(main, "base.txt");
  toMirror(main, "dev", "main");
  // Merged into dev, picked into dev, and work dev lacks.
  git(["switch", "-qc", "merged"]);
  const merged = commit(main, "merged.txt");
  git(["switch", "-qc", "picked", base]);
  const picked = commit(main, "picked.txt");
  git(["switch", "-qc", "work", base]);
  const work = commit(main, "work.txt");
  const old = new Date(Date.now() - scratchAge - 3_600_000).toISOString();
  git(["switch", "-qc", "run-old", base]);
  const stale = commit(main, "stale.txt", old);
  git(["switch", "-qc", "run-new", base]);
  const recent = commit(main, "recent.txt");
  for (const [tipOf, branch] of [
    [merged, "claude/merged"],
    [picked, "worktree-agent-1"],
    [work, "fix/work"],
    [stale, "run/old"],
    [recent, "run/new"],
    [work, "land/claude/work"],
  ])
    toMirror(main, tipOf, branch);
  // A branch pushed from another clone, whose commit this checkout never saw
  // until dev picked the same change.
  gitIn(dir)(["clone", "-q", bare, other]);
  gitIn(other)(["config", "user.name", "Test"]);
  gitIn(other)(["config", "user.email", "test@example.com"]);
  gitIn(other)(["switch", "-qc", "away", base]);
  const away = commit(other, "away.txt");
  toMirror(other, "away", "claude/away");
  assert.notEqual(git(["cat-file", "-e", away]).status, 0);
  git(["switch", "-q", "dev"]);
  git(["merge", "-q", "--ff-only", merged]);
  git(["cherry-pick", picked]);
  fs.writeFileSync(path.join(main, "away.txt"), "away.txt\n");
  git(["add", "away.txt"]);
  git(["commit", "-qm", "away again"]);
  toMirror(main, "dev", "dev");

  const logged: string[] = [];
  const deps = {
    run: async (cwd: string, command: string, args: string[]) => {
      const ran = spawnSync(command, args, { cwd, encoding: "utf8" });
      return { status: ran.status ?? 1, output: ran.stdout + ran.stderr };
    },
    log: (line: string) => logged.push(line),
  };
  await prune(deps, main, { name: "Mirror", url: bare });
  assert.equal(
    gitIn(bare)(["for-each-ref", "--format=%(refname:short)"]).stdout,
    ["dev", "fix/work", "land/claude/work", "main", "run/new", ""].join("\n"),
  );
  assert.deepEqual(logged, [
    "Deleted from Mirror the branches dev has or a Windows run left: claude/away, claude/merged, run/old, worktree-agent-1.",
    "Mirror also holds fix/work, which dev lacks; delete each there once nothing needs it.",
  ]);
  // Nothing left to delete: only the branch dev lacks is named again.
  logged.length = 0;
  await prune(deps, main, { name: "Mirror", url: bare });
  assert.deepEqual(logged, [
    "Mirror also holds fix/work, which dev lacks; delete each there once nothing needs it.",
  ]);
  // A mirror it cannot reach is reported, never thrown.
  logged.length = 0;
  await prune(deps, main, {
    name: "Gone",
    url: path.join(dir, "missing.git"),
  });
  assert.match(
    logged.join("\n"),
    /^Could not list the branches on Gone, so none were cleaned up there/,
  );
});
