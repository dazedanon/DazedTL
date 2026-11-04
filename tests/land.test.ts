import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  acquireLock,
  gitIn,
  LockBusy,
  lockRef,
  releaseLock,
} from "../scripts/land-lock.mjs";
import { spawnSync } from "node:child_process";
import {
  finishHandOff,
  formatBranch,
  handOff,
  mergeDev,
  readReview,
  reviewedHead,
  timer,
  waitForApp,
  onWindows,
} from "../scripts/land.mjs";
import { addRelease, notesTemplate } from "../scripts/changelog.mjs";

test("a landing waits for a live lock, takes over a dead or unrenewed one and tells the user of a long wait once", async (t) => {
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
    notify: () => assert.fail("told the user of no wait"),
  });
  // Pid 10 lives; after 21 minutes without renewing, it loses the lock anyway.
  let waits = 0;
  const notices: string[] = [];
  const eleven = await acquireLock(git, who(11), {
    ...context,
    wait: async () => {
      waits++;
      clock += 7 * 60_000;
    },
    notify: (line: string) => notices.push(line),
  });
  assert.equal(waits, 3);
  // Once past 5 minutes and once at the end, not on every poll.
  assert.equal(notices.length, 2);
  assert.match(notices[1], /^Took over/);
  assert.equal(eleven.holder.started, new Date(21 * 60_000).toISOString());
  // A waiter with a limit gives up on a live holder rather than wait on.
  await assert.rejects(
    acquireLock(git, who(12), {
      ...context,
      alive: () => true,
      limit: 10 * 60_000,
      wait: async () => {
        clock += 7 * 60_000;
      },
    }),
    LockBusy,
  );
  // The holder it replaced cannot release the new one.
  assert.equal(releaseLock(git, ten), false);
  assert.equal(releaseLock(git, eleven), true);
  assert.equal(git(["rev-parse", "-q", "--verify", lockRef]).stdout, "");
});

test("a landing tells the user once when it starts waiting for their DazedTL and once when it closes", async () => {
  const electron = path.join("/main", "app", "node_modules", "electron");
  let polls = 3;
  let waits = 0;
  const told: string[] = [];
  const waited = await waitForApp(
    "/main",
    {
      processes: () => (polls-- > 0 ? `${electron}/dist/electron .` : ""),
      wait: async () => waits++,
    },
    (line) => told.push(line),
  );
  assert.equal(waited, true);
  assert.equal(waits, 3);
  assert.equal(told.length, 2);
  // A closed DazedTL holds nothing up and tells nothing.
  assert.equal(
    await waitForApp(
      "/main",
      { processes: () => "", wait: async () => assert.fail() },
      () => assert.fail(),
    ),
    false,
  );
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
  write("release/.gitattributes", "/notes.md merge=dazedtl-notes\n");
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

test("merging dev stops on notes that reword a line dev has released, and says which", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  const write = (file: string, text: string) => {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), text);
  };
  const changed = (line: string) =>
    `${notesTemplate}\n### Changed\n\n- ${line}\n`;
  const commit = (message: string) => {
    git(["add", "-A"]);
    git(["commit", "-qm", message]);
  };
  git(["init", "-q", "-b", "dev"]);
  git(["config", "user.name", "Test"]);
  git(["config", "user.email", "test@example.com"]);
  write("release/.gitattributes", "/notes.md merge=dazedtl-notes\n");
  write("release/notes.md", changed("Runs stop."));
  commit("base");
  git(["switch", "-qc", "work"]);
  write("release/notes.md", changed("Runs stop, and costs count."));
  commit("work");
  git(["switch", "-q", "dev"]);
  write("release/notes.md", notesTemplate);
  write(
    "CHANGELOG.md",
    addRelease("", {
      version: "1.0.0",
      date: "2026-01-01",
      sections: [{ kind: "Changed", items: ["Runs stop."] }],
      link: "L",
    }),
  );
  commit("release");
  git(["switch", "-q", "work"]);

  const result = await mergeDev(
    git,
    dir,
    async () => assert.fail(),
    () => {},
  );
  assert.equal(result?.code, 2);
  assert.match(
    result?.report.join("\n") ?? "",
    /conflicts in release\/notes\.md\.[^]*rewords a line 1\.0\.0 released: "Runs stop\."[^]*- Runs stop, and costs count\./,
  );
  // The branch's wording waits in the file to be resolved, not merged away.
  assert.equal(
    fs.readFileSync(path.join(dir, "release/notes.md"), "utf8"),
    changed("Runs stop, and costs count."),
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

test("a landing's review record comes from an independent reviewer and accounts for every finding", () => {
  const record = (value: unknown) => readReview(JSON.stringify(value));
  assert.deepEqual(
    record({
      level: "high",
      reviewer: "independent",
      reviews: 2,
      head: "abc1234",
      findings: [
        { summary: "Off by one", outcome: "fixed", reason: "", review: 1 },
        {
          summary: "Slow loop",
          outcome: "dismissed",
          reason: "Runs once",
          review: 2,
        },
      ],
    }),
    {
      level: "high",
      reviewer: "independent",
      reviews: 2,
      head: "abc1234",
      findings: [
        { summary: "Off by one", outcome: "fixed", review: 1 },
        {
          summary: "Slow loop",
          outcome: "dismissed",
          reason: "Runs once",
          review: 2,
        },
      ],
    },
  );
  // The author's own review, or none, no longer lands a branch.
  const reviewed = { reviewer: "independent", head: "abc1234" };
  for (const unreviewed of [
    { level: "high", head: "abc1234", findings: [] },
    { level: "high", reviewer: "author", head: "abc1234", findings: [] },
    { skipped: "Docs only" },
    null,
  ])
    assert.throws(() => record(unreviewed), /"reviewer": "independent"/);
  assert.throws(
    () => record({ ...reviewed, level: "medium", findings: [] }),
    /level of high/,
  );
  // A name such as HEAD would follow the branch past what was reviewed.
  for (const head of [undefined, "HEAD", "work"])
    assert.throws(
      () => record({ ...reviewed, head, level: "high", findings: [] }),
      /hash of the head commit/,
    );
  assert.throws(
    () =>
      record({
        ...reviewed,
        level: "high",
        findings: [{ summary: "Slow loop", outcome: "dismissed" }],
      }),
    /Finding 1 .* without a reason/,
  );
  // A landing runs at most three reviews, and each finding names one of them.
  for (const reviews of [0, 4, null])
    assert.throws(
      () => record({ ...reviewed, level: "high", reviews, findings: [] }),
      /needs "reviews"/,
    );
  for (const [outcome, review] of [
    ["fixed", 0],
    ["fixed", 1.5],
    ["dismissed", "2"],
    ["dismissed", null],
    ["fixed", 3],
    ["fixed", undefined],
  ])
    assert.throws(
      () =>
        record({
          ...reviewed,
          level: "high",
          reviews: 2,
          findings: [
            { summary: "Off by one", outcome, reason: "Kept", review },
          ],
        }),
      /Finding 1 .* needs a review number from 1 to 2/,
    );
  assert.equal(
    record({ ...reviewed, level: "high", findings: [] }).reviews,
    1,
    "a record from before reviews were counted",
  );
  assert.throws(() => record({ ...reviewed, level: "high" }), /findings list/);
  assert.throws(() => readReview("level: high"), /not JSON/);
});

test("a landing's review covers every commit of the branch but merges of dev and the formatter's", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  git(["init", "-q", "-b", "dev"]);
  git(["config", "user.name", "Test"]);
  git(["config", "user.email", "test@example.com"]);
  const commit = (file: string, text: string, message: string) => {
    fs.writeFileSync(path.join(dir, file), text);
    git(["add", "-A"]);
    git(["commit", "-qm", message]);
    return git(["rev-parse", "HEAD"]).stdout.trim();
  };
  commit("base.txt", "base\n", "base");
  git(["checkout", "-qb", "work"]);
  const reviewed = commit("code.mjs", "let a=1\n", "feat: work");
  // A landing merges dev in and commits what the formatter changed.
  git(["checkout", "-q", "dev"]);
  commit("other.txt", "other\n", "fix: other");
  git(["checkout", "-q", "work"]);
  git(["merge", "-q", "--no-edit", "dev"]);
  const format = async () => {
    fs.writeFileSync(path.join(dir, "code.mjs"), "let a = 1;\n");
    return { status: 0, output: "" };
  };
  assert.equal(await formatBranch(git, dir, format, () => {}), null);
  assert.equal(reviewedHead(git, reviewed.slice(0, 8)), reviewed);
  // A merge of another branch, or a fix made after the review such as for a
  // failed landing, is not reviewed.
  git(["checkout", "-qb", "side", `${reviewed}~1`]);
  commit("side.txt", "side\n", "feat: side");
  git(["checkout", "-q", "work"]);
  git(["merge", "-q", "--no-edit", "side"]);
  commit("code.mjs", "let a = 2;\n", "fix: later");
  assert.throws(
    () => reviewedHead(git, reviewed),
    /head;[^]*\n\w+ fix: later\n\w+ Merge branch 'side' into work$/,
  );
  git(["checkout", "-q", "dev"]);
  const elsewhere = commit("dev.txt", "dev\n", "fix: on dev");
  git(["checkout", "-q", "work"]);
  for (const head of [elsewhere, "no-such-commit"])
    assert.throws(() => reviewedHead(git, head), /not a commit on this branch/);
});

test("a sandboxed worker hands off a checked branch without writing the main checkout, and --finish lands it", async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  const main = path.join(root, "main");
  const clone = path.join(root, "clone");
  const mirror = path.join(root, "mirror.git");
  const dir = path.join(root, "handoff");
  // Undoes the worker's read-only view of the main checkout.
  const writable = () => spawnSync("chmod", ["-R", "u+w", main]);
  t.after(() => {
    writable();
    fs.rmSync(root, { recursive: true, force: true });
  });
  const atMain = gitIn(main);
  const atClone = gitIn(clone);
  const rev = (git: ReturnType<typeof gitIn>, ref: string) =>
    git(["rev-parse", ref]).stdout.trim();
  const commit = (top: string, file: string, text: string) => {
    const git = gitIn(top);
    fs.mkdirSync(path.dirname(path.join(top, file)), { recursive: true });
    fs.writeFileSync(path.join(top, file), text);
    git(["add", "-A"]);
    git(["commit", "-qm", `change ${file}`]);
    return rev(git, "HEAD");
  };
  fs.mkdirSync(main);
  atMain(["init", "-q", "-b", "dev"]);
  atMain(["config", "user.name", "Test"]);
  atMain(["config", "user.email", "test@example.com"]);
  gitIn(root)(["init", "-q", "--bare", mirror]);
  commit(
    main,
    "release/mirrors.json",
    JSON.stringify([{ name: "Mirror", type: "forgejo", url: mirror }]),
  );
  gitIn(root)(["clone", "-q", "--no-hardlinks", main, clone]);
  atClone(["config", "user.name", "Test"]);
  atClone(["config", "user.email", "test@example.com"]);
  atClone(["switch", "-qc", "work"]);
  const reviewFile = path.join(root, "review.json");
  const review = (head: string) =>
    fs.writeFileSync(
      reviewFile,
      JSON.stringify({
        level: "high",
        reviewer: "independent",
        head,
        findings: [],
      }),
    );
  // Git runs for real; the format, test, build and contract scripts pass.
  let appOpen = false;
  const logged: string[] = [];
  const deps = {
    run: async (cwd: string, command: string, args: string[]) => {
      if (command !== "git") return { status: 0, output: "" };
      const ran = spawnSync("git", args, { cwd, encoding: "utf8" });
      return { status: ran.status ?? 1, output: ran.stdout + ran.stderr };
    },
    processes: () =>
      appOpen
        ? `${path.join(main, "app", "node_modules", "electron")}/dist/electron .`
        : "",
    read: null,
    wait: async () => {},
    log: (line: string) => logged.push(line),
    notify: () => {},
    onStop: () => {},
  };
  const handoffFile = path.join(dir, "handoff.json");
  const record = () => JSON.parse(fs.readFileSync(handoffFile, "utf8"));
  const refs = () => atMain(["for-each-ref"]).stdout;
  const finish = () => finishHandOff(main, deps, dir, reviewFile);

  // land.mjs refuses to run on Windows: there, both steps must refuse and change nothing.
  if (onWindows(() => {})) {
    const untouched = refs();
    assert.equal(await handOff(clone, deps, dir), 1);
    assert.equal(await finish(), 1);
    assert.equal(refs(), untouched);
    return;
  }

  // dev moved after the worker branched, so the hand-off merges it in.
  const work = commit(clone, "work.txt", "work\n");
  const base = commit(main, "dev.txt", "dev\n");
  const before = refs();
  spawnSync("chmod", ["-R", "a-w", main]);
  assert.equal(await handOff(clone, deps, dir), 0, logged.join("\n"));
  writable();
  const head = rev(atClone, "HEAD");
  assert.ok(
    logged.includes(`Handed off ${base.slice(0, 7)}..${head.slice(0, 7)}`),
  );
  const handoff = record();
  assert.deepEqual(handoff, { format: 1, branch: "work", head, base });
  assert.equal(refs(), before);
  assert.equal(
    fs.existsSync(path.join(main, ".git", "dazedtl-reviews.jsonl")),
    false,
  );

  // The caller retries later while the user's DazedTL is open.
  review(head);
  appOpen = true;
  assert.equal(await finish(), 4);
  appOpen = false;
  // The review covers exactly the bundle, with nothing after it.
  review(work);
  logged.length = 0;
  assert.equal(await finish(), 1);
  assert.match(logged.join("\n"), /not the hand-off's head/);
  // A bundle holding another head than its record names lands nothing.
  fs.writeFileSync(handoffFile, JSON.stringify({ ...handoff, head: work }));
  logged.length = 0;
  assert.equal(await finish(), 1);
  assert.match(logged.join("\n"), /not the head/);
  fs.writeFileSync(handoffFile, JSON.stringify(handoff));
  review(head);
  // A main checkout with changes of its own takes it later.
  fs.writeFileSync(path.join(main, "dev.txt"), "local\n");
  assert.equal(await finish(), 5);
  atMain(["checkout", "--", "dev.txt"]);
  // A file of the main checkout's own in the branch's way never clears by
  // itself, so it is the hand-off's to fix, not a retry's.
  fs.writeFileSync(path.join(main, "work.txt"), "mine\n");
  assert.equal(await finish(), 1);
  fs.rmSync(path.join(main, "work.txt"));
  assert.equal(refs(), before);

  logged.length = 0;
  assert.equal(await finish(), 0, logged.join("\n"));
  assert.ok(
    logged.includes(`Landed ${base.slice(0, 7)}..${head.slice(0, 7)} on dev`),
  );
  assert.equal(fs.readFileSync(path.join(main, "work.txt"), "utf8"), "work\n");
  assert.equal(rev(gitIn(mirror), "dev"), head);
  const entries = fs
    .readFileSync(path.join(main, ".git", "dazedtl-reviews.jsonl"), "utf8")
    .trim()
    .split("\n");
  assert.equal(entries.length, 1);
  assert.equal(JSON.parse(entries[0]).range, `${base}..${head}`);
  // Only dev moved: the fetched ref and the lock are gone.
  assert.equal(refs(), before.replace(base, head));

  logged.length = 0;
  assert.equal(await handOff(clone, deps, dir), 0);
  assert.ok(
    logged.includes(`Nothing to hand off: dev already has ${head.slice(0, 7)}`),
  );
  assert.equal(fs.existsSync(handoffFile), false);

  // dev moving after the checks sends the worker back to merge it.
  commit(clone, "more.txt", "more\n");
  assert.equal(await handOff(clone, deps, dir), 0, logged.join("\n"));
  assert.equal(record().base, head);
  review(record().head);
  commit(main, "later.txt", "later\n");
  logged.length = 0;
  assert.equal(await finish(), 3);
  assert.match(logged.join("\n"), /^dev moved since the hand-off's checks/m);
});
