import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  acquireLock,
  gitIn,
  lockRef,
  releaseLock,
} from "../scripts/land-lock.mjs";
import { formatBranch, mergeDev, timer } from "../scripts/land.mjs";
import { notesTemplate } from "../scripts/changelog.mjs";

test("a landing waits for a live lock and takes over a dead or unrenewed one", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  git(["init", "-q"]);
  let clock = 0;
  const context = {
    now: () => clock,
    namespace: "pid:[1]",
    alive: (pid: number) => pid === 10,
  };
  const who = (pid: number) => ({ pid, branch: `work-${pid}`, worktree: dir });
  await acquireLock(git, who(9), context);
  // Pid 9 is gone, so the next lander takes over at once.
  const ten = await acquireLock(git, who(10), {
    ...context,
    wait: async () => assert.fail("waited for a dead holder"),
  });
  // Pid 10 lives; after 21 minutes without renewing, it loses the lock anyway.
  let waits = 0;
  const eleven = await acquireLock(git, who(11), {
    ...context,
    wait: async () => {
      waits++;
      clock += 7 * 60_000;
    },
  });
  assert.equal(waits, 3);
  assert.equal(eleven.holder.started, new Date(21 * 60_000).toISOString());
  // The holder it replaced cannot release the new one.
  assert.equal(releaseLock(git, ten), false);
  assert.equal(releaseLock(git, eleven), true);
  assert.equal(git(["rev-parse", "-q", "--verify", lockRef]).stdout, "");
});

test("a landing's timing line gives the total and each stage reached", () => {
  let clock = 0;
  const time = timer(() => clock);
  clock = 4_000;
  time.lap("lock wait");
  clock = 5_000;
  time.lap("merge");
  clock = 95_400;
  time.lap("test");
  assert.equal(
    time.summary(),
    "Took 95 s: lock wait 4 s, merge 1 s, test 90 s.",
  );
});

test("a conflicting merge of dev stays in progress with the release notes merged by kind", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  const write = (file: string, text: string) => {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), text);
  };
  const notes = (...fixed: string[]) =>
    `${notesTemplate}\n### Fixed\n\n${fixed.map((line) => `- ${line}`).join("\n")}\n`;
  const commit = (message: string) => {
    git(["add", "-A"]);
    git(["commit", "-qm", message]);
  };
  git(["init", "-q", "-b", "dev"]);
  git(["config", "user.name", "Test"]);
  git(["config", "user.email", "test@example.com"]);
  write(".gitattributes", "release/notes.md merge=dazedtl-notes\n");
  write("release/notes.md", notes("Base."));
  write("code.py", "value = 0\n");
  commit("base");
  git(["switch", "-qc", "work"]);
  write("release/notes.md", notes("Base.", "Work."));
  write("code.py", "value = 1\n");
  commit("work");
  git(["switch", "-q", "dev"]);
  write("release/notes.md", notes("Base.", "Dev."));
  write("code.py", "value = 2\n");
  commit("dev");
  git(["switch", "-q", "work"]);

  const result = await mergeDev(
    git,
    dir,
    async () => assert.fail(),
    () => {},
  );
  assert.equal(result?.code, 2);
  assert.match(result?.report.join("\n") ?? "", /conflicts in code\.py\./);
  // Only the real conflict is left to resolve; a merge run again by hand
  // would conflict on the notes too.
  assert.equal(
    git(["diff", "--name-only", "--diff-filter=U"]).stdout,
    "code.py\n",
  );
  assert.equal(
    fs.readFileSync(path.join(dir, "release/notes.md"), "utf8"),
    notes("Base.", "Dev.", "Work."),
  );
});

test("a landing commits what the formatter changed, and only that", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  git(["init", "-q", "-b", "work"]);
  git(["config", "user.name", "Test"]);
  git(["config", "user.email", "test@example.com"]);
  fs.writeFileSync(path.join(dir, "code.mjs"), "let a=1\n");
  git(["add", "-A"]);
  git(["commit", "-qm", "work"]);
  // The stand-in formatter rewrites the file the way Prettier would.
  const format = async () => {
    fs.writeFileSync(path.join(dir, "code.mjs"), "let a = 1;\n");
    return { status: 0, output: "" };
  };
  assert.equal(await formatBranch(git, dir, format, () => {}), null);
  assert.equal(git(["log", "-1", "--format=%s"]).stdout, "style: format\n");
  assert.equal(git(["status", "--porcelain"]).stdout, "");
  // A formatted branch gets no commit.
  assert.equal(await formatBranch(git, dir, format, () => {}), null);
  assert.equal(git(["rev-list", "--count", "HEAD"]).stdout, "2\n");
});
