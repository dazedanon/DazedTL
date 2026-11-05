import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  acquireLock,
  changedPaths,
  evaluationCommand,
  evaluationDue,
  gitIn,
  LockBusy,
  lockRef,
  platformSensitive,
  releaseLock,
  riskPaths,
} from "../scripts/land-lock.mjs";
import { spawnSync } from "node:child_process";
import {
  branchCI,
  finishHandOff,
  formatBranch,
  handOff,
  land,
  mergeDev,
  readReview,
  reviewedHead,
  timer,
  unevaluated,
  untrailedFixes,
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

test("a landing's review record holds its evaluation, or the criteria its author checked where none is due", () => {
  const record = (value: unknown) => readReview(JSON.stringify(value));
  assert.deepEqual(
    record({
      reviewer: "independent",
      reviews: 2,
      head: "abc1234",
      e2e: ["translated  --game choice-help+playable", "live"],
      findings: [
        {
          summary: "Off by one",
          severity: "blocking",
          outcome: "fixed",
          reason: "",
          review: 1,
        },
        { summary: "Typo", severity: "minor", outcome: "fixed", review: 2 },
        {
          summary: "Slow loop",
          severity: "minor",
          outcome: "overruled",
          reason: "The user keeps it",
          review: 2,
        },
      ],
    }),
    {
      reviewer: "independent",
      reviews: 2,
      head: "abc1234",
      e2e: ["translated --game choice-help+playable", "live"],
      findings: [
        {
          summary: "Off by one",
          severity: "blocking",
          outcome: "fixed",
          review: 1,
        },
        { summary: "Typo", severity: "minor", outcome: "fixed", review: 2 },
        {
          summary: "Slow loop",
          severity: "minor",
          outcome: "overruled",
          reason: "The user keeps it",
          review: 2,
        },
      ],
    },
  );
  // The author's own review no longer lands a branch.
  const evaluated = { reviewer: "independent", head: "abc1234", e2e: [] };
  for (const unreviewed of [
    { level: "high", head: "abc1234", findings: [] },
    { level: "high", reviewer: "author", head: "abc1234", findings: [] },
    { skipped: "Docs only" },
    null,
  ])
    assert.throws(() => record(unreviewed), /"reviewer": "independent"/);
  // A name such as HEAD would follow the branch past what was checked.
  for (const head of [undefined, "HEAD", "work"])
    assert.throws(
      () => record({ ...evaluated, head, findings: [] }),
      /hash of the head commit/,
    );
  // Every finding is fixed unless the user overrules it, with their reason.
  for (const outcome of ["dismissed", "overruled"])
    assert.throws(
      () =>
        record({
          ...evaluated,
          findings: [{ summary: "Slow loop", severity: "minor", outcome }],
        }),
      outcome === "dismissed"
        ? /Finding 1 .* needs an outcome of fixed, or overruled/
        : /Finding 1 .* overruled without a reason/,
    );
  // Each finding names the evaluation that reported it; more than three ran
  // only when the user let a landing go on after its third FAIL, as the
  // Discord intake's record of a landing saved mid-loop before evaluations
  // also shows, with the kinds of the time.
  for (const reviews of [0, 1.5, null])
    assert.throws(
      () => record({ ...evaluated, reviews, findings: [] }),
      /needs "reviews", how many evaluations ran, a whole number from 1/,
    );
  assert.equal(
    readReview(
      JSON.stringify({
        reviewer: "independent",
        reviews: 4,
        head: "abc1234",
        findings: [
          { summary: "A", kind: "risk", outcome: "fixed", review: 1 },
          { summary: "B", severity: "minor", outcome: "fixed", review: 4 },
        ],
      }),
      { intake: true },
    ).reviews,
    4,
  );
  for (const review of [0, 1.5, "2", null, 3, undefined])
    assert.throws(
      () =>
        record({
          ...evaluated,
          reviews: 2,
          findings: [
            {
              summary: "Off by one",
              severity: "minor",
              outcome: "fixed",
              review,
            },
          ],
        }),
      /Finding 1 .* needs a review number from 1 to 2/,
    );
  for (const finding of [
    { summary: "Off by one", outcome: "fixed" },
    { summary: "Off by one", severity: "nit", outcome: "fixed" },
    { summary: "Off by one", kind: "nit", outcome: "fixed" },
  ])
    assert.throws(
      () => record({ ...evaluated, findings: [finding] }),
      /Finding 1 .* needs a severity of blocking or minor/,
    );
  // A FAIL's fixes land only once a fresh evaluator re-checked them; after
  // the third, only the user's overrule lands it.
  const blocking = (review: number, outcome = "fixed") => ({
    summary: "Breaks Undo",
    severity: "blocking",
    outcome,
    reason: "The user keeps it",
    review,
  });
  assert.throws(
    () => record({ ...evaluated, findings: [blocking(1)] }),
    /Evaluation 1 failed: a fresh evaluator re-checks its blocking findings/,
  );
  assert.throws(
    () => record({ ...evaluated, reviews: 3, findings: [blocking(3)] }),
    /Evaluation 3 failed, the last of 3: stop and report to the user/,
  );
  for (const findings of [
    [blocking(1)],
    [blocking(1), { ...blocking(2), severity: "minor" }],
    [blocking(1), blocking(2, "overruled")],
  ])
    assert.equal(
      record({ ...evaluated, reviews: 2, findings }).findings.length,
      findings.length,
    );
  assert.equal(
    record({ ...evaluated, reviews: 3, findings: [blocking(3, "overruled")] })
      .reviews,
    3,
  );
  // The intake's records are held to the same rule, and carry no E2E runs,
  // which its worker names in the hand-off.
  const intakeRecord = {
    reviewer: "independent",
    head: "abc1234",
    findings: [{ summary: "Typo", severity: "minor", outcome: "fixed" }],
  };
  assert.deepEqual(readReview(JSON.stringify(intakeRecord), { intake: true }), {
    ...intakeRecord,
    reviews: 1,
    findings: [
      { summary: "Typo", severity: "minor", outcome: "fixed", review: 1 },
    ],
  });
  assert.throws(
    () =>
      readReview(JSON.stringify({ ...intakeRecord, findings: [blocking(1)] }), {
        intake: true,
      }),
    /Evaluation 1 failed/,
  );
  assert.throws(
    () => record(intakeRecord),
    /names the scenarios and live test its author ran as "e2e"/,
  );
  // Where no evaluation is due, the record holds the criteria its author
  // checked, and no findings.
  const unevaluatedRecord = {
    reviewer: "none",
    head: "abc1234",
    criteria: [" Docs say the new rule "],
    whyNoE2e: "Docs only",
  };
  assert.deepEqual(record(unevaluatedRecord), {
    reviewer: "none",
    reviews: 0,
    head: "abc1234",
    criteria: ["Docs say the new rule"],
    e2e: [],
    whyNoE2e: "Docs only",
    findings: [],
  });
  for (const criteria of [undefined, [], [" "], "Docs"])
    assert.throws(
      () => record({ ...unevaluatedRecord, criteria }),
      /needs "criteria", each acceptance criterion its author checked/,
    );
  assert.throws(
    () => record({ ...unevaluatedRecord, findings: [blocking(1)] }),
    /no evaluation has no findings/,
  );
  // Older records still read: a code-review level, kinds with dismissals,
  // marks and lenses, and up to three reviews.
  assert.deepEqual(
    record({
      ...evaluated,
      level: "high",
      reviews: 3,
      lenses: ["places-and-chains", "live-check"],
      findings: [
        {
          summary: "Off by one",
          kind: "bug",
          outcome: "fixed",
          userFacing: true,
          review: 1,
        },
        {
          summary: "Typo",
          kind: "quality",
          outcome: "dismissed",
          reason: "Fine",
          behavior: false,
          review: 3,
        },
      ],
    }),
    {
      ...evaluated,
      reviews: 3,
      findings: [
        { summary: "Off by one", kind: "bug", outcome: "fixed", review: 1 },
        {
          summary: "Typo",
          kind: "quality",
          outcome: "dismissed",
          reason: "Fine",
          review: 3,
        },
      ],
    },
  );
  // E2E runs are scenario.mjs's own arguments, with names it knows, or a
  // reason none ran.
  assert.deepEqual(
    record({ ...evaluated, e2e: undefined, whyNoE2e: " Docs ", findings: [] })
      .whyNoE2e,
    "Docs",
  );
  for (const [e2e, problem] of [
    [["no-such-scenario"], /no-such-scenario is no scenario/],
    [["translated --game choice-help+nope"], /nope is no game variant/],
    [["translated --game choice-help+"], /an empty name is no game variant/],
    [["translated --app"], /names --app; leave it out/],
    [["live --work logs"], /names --work; leave it out/],
    [["translated --nope x"], /takes --game and --from once each, not --nope/],
    [["translated --game mz --game mv"], /once each, not --game/],
    [["live --upgrade-from"], /gives --upgrade-from no value/],
    [["live --game mz"], /takes --upgrade-from once each/],
    [[""], /a run is no text/],
    ["live", /names the scenarios/],
  ] as const)
    assert.throws(() => record({ ...evaluated, e2e, findings: [] }), problem);
  assert.throws(
    () =>
      record({ ...evaluated, e2e: ["live"], whyNoE2e: "Docs", findings: [] }),
    /keep one/,
  );
  assert.throws(
    () => record({ ...evaluated, whyNoE2e: " ", findings: [] }),
    /"whyNoE2e" is empty/,
  );
  assert.throws(() => record(evaluated), /findings list/);
  assert.throws(() => readReview("level: high"), /not JSON/);
  // A record saying none was due holds only where the rule marks nothing.
  const none = record(unevaluatedRecord);
  assert.equal(unevaluated(none, ["docs/development.md"]), null);
  assert.equal(
    unevaluated(record({ ...evaluated, findings: [] }), ["scripts/land.mjs"]),
    null,
  );
  assert.match(
    unevaluated(none, ["docs/development.md", "app/src/ui/Row.tsx"]) ?? "",
    /marks this branch \(UI: app\/src\/ui\/Row\.tsx\)/,
  );
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

test("a landing refuses a fix of its own without the trailers saying where its bug came from and who found it", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  git(["init", "-q", "-b", "dev"]);
  git(["config", "user.name", "Test"]);
  git(["config", "user.email", "test@example.com"]);
  const commit = (message: string) => {
    fs.writeFileSync(path.join(dir, "code.txt"), message);
    git(["commit", "-qam", message]);
    return git(["rev-parse", "HEAD"]).stdout.trim();
  };
  fs.writeFileSync(path.join(dir, "code.txt"), "");
  git(["add", "-A"]);
  git(["commit", "-qm", "base"]);
  git(["checkout", "-qb", "work"]);
  const work = commit("feat: work");
  // dev's fixes landed under their own checks, so a merge of dev brings
  // in none the branch must answer for.
  git(["checkout", "-q", "dev"]);
  const elsewhere = commit("fix: on dev");
  git(["checkout", "-q", "work"]);
  git(["merge", "-q", "--no-edit", "-X", "theirs", "dev"]);
  assert.equal(untrailedFixes(git, "dev"), null);
  commit("fix(ui): bare");
  const reviewFile = path.join(dir, "..", `${path.basename(dir)}.json`);
  t.after(() => fs.rmSync(reviewFile, { force: true }));
  fs.writeFileSync(
    reviewFile,
    JSON.stringify({
      level: "high",
      reviewer: "independent",
      head: work,
      e2e: [],
      findings: [],
    }),
  );
  const logged: string[] = [];
  const deps = { log: (line: string) => logged.push(line) } as any;
  if (!onWindows(() => {})) {
    assert.equal(await land(dir, deps, reviewFile), 1);
    assert.match(
      logged.join("\n"),
      /lack the trailers[^]*\n\w{7} fix\(ui\): bare: no Introduced-by trailer; no Found-by trailer\n[^]*review, ci, scenario, playtest, discord, user, author[^]*new head in the review record/,
    );
  }
  const reword = (...trailers: string[]) =>
    git([
      "commit",
      "-q",
      "--amend",
      "-m",
      "fix(ui): bare",
      "-m",
      trailers.join("\n"),
    ]);
  // A note may follow a value, and a commit of the branch's own may be named.
  reword("Introduced-by: unknown, before the history", "Found-by: Discord");
  assert.equal(untrailedFixes(git, "dev"), null);
  // A record saying no evaluation was due lands no branch the evaluation
  // rule marks.
  if (!onWindows(() => {})) {
    fs.mkdirSync(path.join(dir, "scripts"));
    fs.writeFileSync(path.join(dir, "scripts", "land.mjs"), "x\n");
    git(["add", "-A"]);
    git(["commit", "-qm", "feat: tooling"]);
    fs.writeFileSync(
      reviewFile,
      JSON.stringify({
        reviewer: "none",
        head: git(["rev-parse", "HEAD"]).stdout.trim(),
        criteria: ["The tooling works"],
        e2e: [],
      }),
    );
    logged.length = 0;
    assert.equal(await land(dir, deps, reviewFile), 1);
    assert.match(
      logged.join("\n"),
      /evaluation rule marks this branch \(shared infrastructure: scripts\/land\.mjs\), so it lands only once an evaluator checked it/,
    );
    git(["reset", "-q", "--hard", "HEAD~1"]);
  }
  reword(`Introduced-by: ${work.slice(0, 8)}`, "Found-by: review");
  assert.equal(untrailedFixes(git, "dev"), null);
  // A commit named beside none says two things at once.
  reword("Introduced-by: none", `Introduced-by: ${work}`, "Found-by: review");
  assert.match(
    untrailedFixes(git, "dev") ?? "",
    /bare: Introduced-by none beside other values/,
  );
  reword(
    "Introduced-by: v2.61.0",
    `Introduced-by: ${elsewhere}`,
    "Found-by: somebody",
  );
  const refused = untrailedFixes(git, "refs/heads/dev") ?? "";
  assert.match(
    refused,
    /Introduced-by "v2\.61\.0" is no commit hash, unknown or none/,
  );
  assert.match(refused, /Found-by "somebody" is none of review,/);
  // dev's commit is merged in, so it is before the fix.
  assert.doesNotMatch(refused, new RegExp(`Introduced-by ${elsewhere}`));
  reword("Introduced-by: deadbeef1", "Found-by: user", "Found-by: ci");
  assert.match(
    untrailedFixes(git, "dev") ?? "",
    /2 Found-by trailers, not the one that found it; Introduced-by deadbeef1 names no commit Git can find/,
  );
});

test("a sandboxed worker hands off a checked branch without writing the main checkout, and --finish lands it", async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  const main = path.join(root, "main");
  const clone = path.join(root, "clone");
  const mirror = path.join(root, "mirror.git");
  const github = path.join(root, "github.git");
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
  gitIn(root)(["init", "-q", "--bare", github]);
  commit(
    main,
    "release/mirrors.json",
    JSON.stringify([
      { name: "Mirror", type: "forgejo", url: mirror },
      { name: "GitHub", type: "github", url: `file://${github}` },
    ]),
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
  const pushed = () =>
    gitIn(github)([
      "rev-parse",
      "-q",
      "--verify",
      "refs/heads/land/work",
    ]).stdout.trim();
  const stand = standInGitHub(
    new URL(`file://${github}`).pathname.replace(/^\/|\.git$/g, ""),
    pushed,
    "success",
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
    read: stand.read,
    write: stand.write,
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
  commit(clone, "scripts/setup.mjs", "setup\n");
  commit(clone, "scripts/land.mjs", "land\n");
  const base = commit(main, "dev.txt", "dev\n");
  const before = refs();
  spawnSync("chmod", ["-R", "a-w", main]);
  // The worker names the E2E it ran, and the reviews log keeps it.
  const ran = { e2e: ["translated --game playable --from HEAD~1", "live"] };
  assert.equal(await handOff(clone, deps, dir, ran), 0, logged.join("\n"));
  writable();
  const head = rev(atClone, "HEAD");
  assert.ok(
    logged.includes(`Handed off ${base.slice(0, 7)}..${head.slice(0, 7)}`),
  );
  const handoff = record();
  assert.deepEqual(handoff, { format: 1, branch: "work", head, base, ...ran });
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
  // --finish keeps the names the worker's land.mjs checked against its own
  // branch, which may add a scenario dev lacks.
  const named = { ...handoff, e2e: [...ran.e2e, "added-by-the-branch"] };
  fs.writeFileSync(handoffFile, JSON.stringify(named));
  // A record saying no evaluation was due lands no hand-off the evaluation
  // rule marks, and starts no CI.
  fs.writeFileSync(
    reviewFile,
    JSON.stringify({ reviewer: "none", head, criteria: ["Works"] }),
  );
  logged.length = 0;
  assert.equal(await finish(), 1);
  assert.match(
    logged.join("\n"),
    /evaluation rule marks this branch \(shared infrastructure: scripts\/land\.mjs\)/,
  );
  assert.deepEqual(stand.writes, []);
  review(head);
  // The hand-off changes a platform-sensitive path, so it lands once CI on
  // GitHub passes: --finish starts it and is run again later.
  assert.equal(await finish(), 5);
  assert.equal(pushed(), head);
  assert.deepEqual(stand.writes, ["workflows/ci.yml/dispatches"]);
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
  assert.equal(pushed(), "");

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
  assert.deepEqual(JSON.parse(entries[0]).e2e, named.e2e);
  // Only dev moved: the fetched ref and the lock are gone.
  assert.equal(refs(), before.replace(base, head));

  logged.length = 0;
  assert.equal(await handOff(clone, deps, dir), 0);
  assert.ok(
    logged.includes(`Nothing to hand off: dev already has ${head.slice(0, 7)}`),
  );
  assert.equal(fs.existsSync(handoffFile), false);

  // dev moving after the checks sends the worker back to merge it, but only
  // once the hand-off's CI has passed, which then stands after that merge.
  commit(clone, "scripts/setup.mjs", "more\n");
  // A platform-sensitive hand-off names the E2E its worker ran, or says why
  // none fits, before anything runs.
  logged.length = 0;
  assert.equal(await handOff(clone, deps, dir), 1);
  assert.match(
    logged.join("\n"),
    /platform-sensitive paths \(scripts\/setup\.mjs\)[^]*--why-no-e2e/,
  );
  assert.equal(fs.existsSync(handoffFile), false);
  const why = "The intake runs the worker's runs itself.";
  assert.equal(
    await handOff(clone, deps, dir, { whyNoE2e: why }),
    0,
    logged.join("\n"),
  );
  assert.deepEqual(record().e2e, []);
  assert.equal(record().whyNoE2e, why);
  assert.equal(record().base, head);
  review(record().head);
  // --finish refuses a record naming neither, as one written before they
  // were named, before CI starts.
  const reasoned = record();
  const { e2e: _e2e, whyNoE2e: _why, ...unnamed } = reasoned;
  fs.writeFileSync(handoffFile, JSON.stringify(unnamed));
  const dispatched = stand.writes.length;
  logged.length = 0;
  assert.equal(await finish(), 1);
  assert.match(logged.join("\n"), /its hand-off names each scenario/);
  assert.equal(stand.writes.length, dispatched);
  fs.writeFileSync(handoffFile, JSON.stringify(reasoned));
  commit(main, "later.txt", "later\n");
  assert.equal(await finish(), 5);
  logged.length = 0;
  assert.equal(await finish(), 3);
  assert.match(logged.join("\n"), /^dev moved since the hand-off's checks/m);
  // A run with a name scenario.mjs doesn't know is refused, and leaves no
  // earlier hand-off behind to finish.
  logged.length = 0;
  assert.equal(await handOff(clone, deps, dir, { e2e: ["live --nope"] }), 1);
  assert.match(logged.join("\n"), /not --nope/);
  assert.equal(fs.existsSync(handoffFile), false);

  // A fix without its trailers is refused before anything else runs.
  commit(clone, "fix.txt", "fix\n");
  atClone(["commit", "-q", "--amend", "-m", "fix: unexplained"]);
  logged.length = 0;
  assert.equal(await handOff(clone, deps, dir), 1);
  assert.match(
    logged.join("\n"),
    /fix: unexplained: no Introduced-by[^]*Then hand off again\.$/,
  );
  assert.equal(fs.existsSync(handoffFile), false);
});

test("the platform rule marks every file a fix for Windows alone changed since 2026-09-15, and no other change", () => {
  // Each with the fix that changed it.
  const changed = [
    "START.sh", // 65720c07
    "scripts/bootstrap.ps1", // 65720c07
    "scripts/setup.mjs", // 65720c07
    "app/electron/main.cjs",
    "backend/dazedtl/system.py", // 3bb96dea
    "backend/dazedtl/stdio.py", // e0c1be6d
    "backend/dazedtl/translation/helper_command.py", // 3bb96dea
    "backend/dazedtl/translation/jobs.py", // 0f0c513f
    "backend/dazedtl/translation/ownership.py", // 0c98dc8a
    "backend/dazedtl/translation/files.py", // 70e017c5
    "backend/dazedtl/translation/release.py", // 0d9685fb
    "backend/dazedtl/translation/context_setup.py", // bed881be
    "backend/dazedtl/translation/start_over.py", // 3b11b377
    "backend/dazedtl/images/service.py", // fa247ab1
    "backend/dazedtl/compatibility/images.py", // bed881be
    "backend/dazedtl/compatibility/checkpoints.py", // b24adcff
    "backend/dazedtl/compatibility/checkpoint_commits.py", // b8b64a0d
    "backend/dazedtl/compatibility/game_write.py", // b8b64a0d
    "backend/dazedtl/compatibility/workflow_worker.py", // 849c37ab
    "backend/dazedtl/compatibility/manual_worker.py", // e0c1be6d
    "backend/dazedtl/engine/desktop/backend/manual.py", // cf3626b7
    "backend/dazedtl/engine/util/paths.py", // cdeb9094
    "backend/dazedtl/engine/util/subprocess_runner.py", // bbef7573
    "backend/dazedtl/engine/util/translation_task.py", // e0c1be6d
    "backend/dazedtl/engine/util/ace/rv2json.py", // 1da2d874
    "backend/dazedtl/engine/util/ace/game_ini.py", // 0fe0ae22
    "backend/dazedtl/engine/gameupdate/gameupdate/patch.ps1", // 1082c082
    "backend/dazedtl/engine/data/skills/game-translation/tools/Game Archives/KiriKiri XP3/pack_xp3.py", // bd5b26ca
    "scripts/project.py", // a895322f
    "scripts/qa_upgrade.py",
    "scripts/testkit/group.mjs", // aae8644d
    "scripts/testkit/scenarios.mjs",
    ".github/workflows/ci.yml",
  ];
  const elsewhere = [
    "scripts/land.mjs",
    "app/src/features/guided/progress.ts",
    "backend/dazedtl/engine/modules/rpgmakermvmz.py",
    "backend/dazedtl/engine/data/skills/game-translation/SKILL.md",
    "docs/development.md",
    "tests/test_images.py",
  ];
  assert.deepEqual(platformSensitive([...elsewhere, ...changed]), changed);
});

test("a branch gets an evaluation for each risk its paths or its author mark, which the evaluation command lists", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-evaluation-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  git(["init", "-q", "-b", "dev"]);
  git(["config", "user.email", "test@example.com"]);
  git(["config", "user.name", "Test"]);
  git(["commit", "-q", "--allow-empty", "-m", "feat: base"]);
  git(["switch", "-q", "-c", "work"]);
  const write = (file: string) => {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), "x\n");
    git(["add", file]);
    git(["commit", "-q", "-m", `feat: ${file}`]);
  };
  write("backend/dazedtl/engine/modules/rpgmakermvmz.py");
  write("tests/app.test.ts");
  // A backend API change writes the generated contracts again.
  write("app/src/api/contracts.ts");
  write("docs/architecture.md");
  write("app/tsconfig.json");
  const none =
    "This branch changes no path the evaluation rule marks: unless you mark it a multi-area rework or over about an hour of building, its checks and your checked criteria land it.";
  assert.deepEqual(evaluationCommand(git, ["evaluation", "dev", "work"]), {
    code: 0,
    lines: [
      none,
      "It changes no screen or user flow, so the Live check is not due.",
    ],
  });
  // What no path shows, its author marks.
  assert.deepEqual(
    evaluationDue(changedPaths(git, "dev", "work"), {
      marked: ["multi-area rework"],
    }),
    [{ risk: "multi-area rework", files: [] }],
  );
  write("backend/dazedtl/projects/store.py");
  write("backend/dazedtl/compatibility/batch_control.py");
  write("backend/dazedtl/translation/ownership.py");
  write("backend/dazedtl/settings/store.py");
  write("app/src/ui/Row.tsx");
  write("scripts/land.mjs");
  assert.deepEqual(evaluationCommand(git, ["evaluation", "dev", "work"]), {
    code: 0,
    lines: [
      "This branch gets an evaluation before it lands, for these risks:",
      "  saved data:",
      "    backend/dazedtl/projects/store.py",
      "  paid work:",
      "    backend/dazedtl/compatibility/batch_control.py",
      "  run ownership:",
      "    backend/dazedtl/translation/ownership.py",
      "  credentials:",
      "    backend/dazedtl/settings/store.py",
      "  UI:",
      "    app/src/ui/Row.tsx",
      "  shared infrastructure:",
      "    scripts/land.mjs",
      "It changes a screen or user flow, so its evaluation runs the Live check.",
    ],
  });
  // A ref Git can't find never reads as a branch with nothing to evaluate.
  assert.equal(evaluationCommand(git, ["evaluation", "dev", "nope"]).code, 2);
  assert.equal(evaluationCommand(git, ["evaluation", "dev"]).code, 2);
  assert.equal(evaluationCommand(git, ["screens", "dev", "work"]).code, 2);
  // Nor do refs Git can't compare, such as an orphan branch's.
  git(["switch", "-q", "--orphan", "orphan"]);
  write("app/src/ui/Orphan.tsx");
  assert.equal(evaluationCommand(git, ["evaluation", "dev", "orphan"]).code, 2);
  assert.throws(
    () => changedPaths(git, "dev", "orphan"),
    /Git can't list what orphan changes since dev/,
  );
  // Each risk's paths name files the repository has, so a rename never
  // leaves a risk quietly unwatched.
  const tracked = gitIn(path.join(import.meta.dirname, ".."))(["ls-files"])
    .stdout.split("\n")
    .filter(Boolean);
  for (const { risk, paths } of riskPaths)
    for (const pattern of paths)
      assert.ok(
        tracked.some((file) => pattern.test(file)),
        `${risk}: ${pattern} matches no tracked file`,
      );
});

/**
 * A stand-in GitHub whose dispatched CI runs end as `first`, failing unless
 * said, and pass on a rerun.
 */
function standInGitHub(repo: string, pushed: () => string, first = "failure") {
  const runs: any[] = [];
  const writes: string[] = [];
  const add = (sha: string, conclusion: string, attempt: number) =>
    runs.push({
      id: runs.length + 1,
      head_sha: sha,
      head_branch: "land/work",
      path: ".github/workflows/ci.yml",
      status: "completed",
      conclusion,
      run_attempt: attempt,
      html_url: `https://github.test/runs/${runs.length + 1}`,
      created_at: new Date(1000 + runs.length).toISOString(),
    });
  const read = async (route: string) => {
    const sha = /head_sha=(\w+)/.exec(route)?.[1];
    if (sha)
      return { workflow_runs: runs.filter((run) => run.head_sha === sha) };
    if (route.endsWith("/jobs?per_page=100"))
      return {
        jobs: [
          { name: "Checks (ubuntu-24.04)", conclusion: "success" },
          {
            name: "Scenarios images-kirikiri (windows-2025)",
            conclusion: "failure",
          },
        ],
      };
    const id = Number(/runs\/(\d+)$/.exec(route)?.[1]);
    return runs.find((run) => run.id === id) ?? null;
  };
  // Errors the next writes throw, as GitHub's refusals do.
  const refusals: string[] = [];
  const write = async (route: string, request?: { body?: any }) => {
    writes.push(route.replace(`repos/${repo}/actions/`, ""));
    const refused = refusals.shift();
    if (refused) throw new Error(`GitHub answered ${refused} for ${route}.`);
    if (route.endsWith("/dispatches")) add(pushed(), first, 1);
    else Object.assign(runs.at(-1), { conclusion: "success", run_attempt: 2 });
    assert.equal(request?.body?.ref ?? "land/work", "land/work");
    return null;
  };
  return { runs, writes, refusals, add, read, write };
}

test("a platform-sensitive branch lands once CI on GitHub passes, after one rerun of a first failure, and never on red", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const main = path.join(dir, "main");
  const work = path.join(dir, "work");
  const mirror = path.join(dir, "github.git");
  fs.mkdirSync(main);
  const atMain = gitIn(main);
  const git = gitIn(work);
  gitIn(dir)(["init", "-q", "--bare", mirror]);
  atMain(["init", "-q", "-b", "dev"]);
  atMain(["config", "user.name", "Test"]);
  atMain(["config", "user.email", "test@example.com"]);
  const commit = (top: string, file: string, text: string) => {
    fs.mkdirSync(path.dirname(path.join(top, file)), { recursive: true });
    fs.writeFileSync(path.join(top, file), text);
    gitIn(top)(["add", "-A"]);
    gitIn(top)(["commit", "-qm", `change ${file}`]);
    return gitIn(top)(["rev-parse", "HEAD"]).stdout.trim();
  };
  const url = `file://${mirror}`;
  commit(
    main,
    "release/mirrors.json",
    JSON.stringify([{ name: "GitHub", type: "github", url }]),
  );
  atMain(["worktree", "add", "-q", "-b", "work", work]);
  const pushed = () =>
    gitIn(mirror)([
      "rev-parse",
      "-q",
      "--verify",
      "refs/heads/land/work",
    ]).stdout.trim();
  const github = standInGitHub(
    new URL(url).pathname.replace(/^\/|\.git$/g, ""),
    pushed,
  );
  const logged: string[] = [];
  const realGit = (cwd: string, args: string[]) => {
    const ran = spawnSync("git", args, { cwd, encoding: "utf8" });
    return { status: ran.status ?? 1, output: ran.stdout + ran.stderr };
  };
  // The scripts a landing ran and the CI runs it started, in order.
  const ran: string[] = [];
  const deps = {
    // Git runs for real; the format, test and build scripts pass.
    run: async (cwd: string, command: string, args: string[]) => {
      if (command === "git") return realGit(cwd, args);
      ran.push(path.basename(args[0]));
      return { status: 0, output: "" };
    },
    processes: () => "",
    read: github.read,
    write: (route: string, request?: { body?: any }) => {
      if (route.endsWith("/dispatches")) ran.push("CI");
      return github.write(route, request);
    },
    wait: async () => {},
    log: (line: string) => logged.push(line),
    notify: () => {},
    onStop: () => {},
  };
  const reviewFile = path.join(dir, "review.json");
  const landReviewed = (head: string, e2e = ["live"]) => {
    fs.writeFileSync(
      reviewFile,
      JSON.stringify({
        level: "high",
        reviewer: "independent",
        head,
        e2e,
        findings: [],
      }),
    );
    logged.length = 0;
    return land(work, deps, reviewFile);
  };
  const dev = () => atMain(["rev-parse", "dev"]).stdout.trim();
  // land.mjs refuses to run on Windows, before it reads anything.
  if (onWindows(() => {})) {
    assert.equal(await landReviewed(dev()), 1);
    assert.deepEqual(github.writes, []);
    return;
  }

  const first = commit(work, "scripts/setup.mjs", "one\n");
  // Its record names the E2E its author ran, or says why none fits, before
  // anything runs.
  assert.equal(await landReviewed(first, []), 1);
  assert.match(
    logged.join("\n"),
    /platform-sensitive paths \(scripts\/setup\.mjs\)[^]*"whyNoE2e"/,
  );
  assert.deepEqual(github.writes, []);
  ran.length = 0;
  assert.equal(await landReviewed(first), 0, logged.join("\n"));
  assert.equal(dev(), first);
  assert.deepEqual(github.writes, [
    "workflows/ci.yml/dispatches",
    "runs/1/rerun-failed-jobs",
  ]);
  assert.equal(github.runs[0].head_sha, first);
  assert.equal(pushed(), "");
  // The local checks run before CI, and not again for the same head.
  assert.deepEqual(ran, ["format.mjs", "test.mjs", "build.mjs", "CI"]);

  // A failure after the rerun stops the landing and names the check.
  const red = commit(work, "scripts/setup.mjs", "two\n");
  github.add(red, "failure", 2);
  assert.equal(await landReviewed(red), 1);
  assert.ok(
    logged.includes(
      `CI failed after one rerun for ${red.slice(0, 7)}, so nothing landed. Failed: Scenarios images-kirikiri on Windows. Fix it, then land work again.`,
    ),
    logged.join("\n"),
  );
  assert.equal(dev(), first);
  assert.equal(github.writes.length, 2);

  // A merge of dev after CI passed needs no second run; --finish, which never
  // waits, starts the rerun of a first failure and comes back later.
  const check = (follow: boolean) =>
    branchCI(deps, {
      git,
      cwd: work,
      main,
      branch: "work",
      tip: git(["rev-parse", "HEAD"]).stdout.trim(),
      sensitive: ["scripts/setup.mjs"],
      follow,
      again: "land work again",
    });
  github.add(commit(work, "scripts/setup.mjs", "three\n"), "success", 1);
  commit(main, "other.txt", "other\n");
  git(["merge", "-q", "--no-edit", "dev"]);
  assert.equal(await check(true), null);
  assert.equal(github.writes.length, 2);
  github.add(commit(work, "scripts/setup.mjs", "four\n"), "failure", 1);
  assert.equal((await check(false))?.code, 5);
  assert.equal(
    github.writes.at(-1),
    `runs/${github.runs.length}/rerun-failed-jobs`,
  );
  // A merge of dev while that rerun runs follows it rather than starting
  // another run, which would cancel it.
  Object.assign(github.runs.at(-1), {
    status: "in_progress",
    conclusion: null,
  });
  commit(main, "later.txt", "later\n");
  git(["merge", "-q", "--no-edit", "dev"]);
  const writes = github.writes.length;
  assert.equal((await check(false))?.code, 5);
  assert.equal(github.writes.length, writes);

  // A run GitHub could not start gets a new one, and a dispatch refused
  // just after the push is sent again; a landing that waits deletes its
  // branch however it ends, and lacking a token, --finish comes back later.
  const stuck = commit(work, "scripts/setup.mjs", "five\n");
  github.add(stuck, "startup_failure", 1);
  github.refusals.push("422", "500");
  assert.equal((await check(true))?.code, 1);
  assert.deepEqual(github.writes.slice(writes), [
    "workflows/ci.yml/dispatches",
    "workflows/ci.yml/dispatches",
  ]);
  assert.equal(pushed(), "");
  // A second run that could not start, as with a broken workflow file, is
  // the branch's to fix: --finish refuses instead of starting runs forever.
  github.add(stuck, "startup_failure", 1);
  const started = github.writes.length;
  const unstartable = await check(false);
  assert.equal(unstartable?.code, 1);
  assert.match(unstartable?.report.at(-1) ?? "", /^CI could not start for /);
  assert.equal(github.writes.length, started);
  const unsigned = { ...deps, read: null, write: null };
  assert.equal(
    (
      await branchCI(unsigned, {
        git,
        cwd: work,
        main,
        branch: "work",
        tip: stuck,
        sensitive: ["scripts/setup.mjs"],
        follow: false,
        again: "hand work off again",
      })
    )?.code,
    5,
  );

  // A merge of dev that resolves a conflict holds work no earlier run
  // checked, so it gets a run of its own.
  github.add(commit(work, "scripts/setup.mjs", "six\n"), "success", 1);
  commit(main, "scripts/setup.mjs", "dev's\n");
  git(["merge", "-q", "--no-edit", "dev"]);
  fs.writeFileSync(path.join(work, "scripts/setup.mjs"), "both\n");
  git(["commit", "-qam", "Merge dev"]);
  const before = github.writes.length;
  assert.equal((await check(false))?.code, 5);
  assert.deepEqual(github.writes.slice(before), [
    "workflows/ci.yml/dispatches",
  ]);
  // Release notes that mergeDev joins by itself are no resolution.
  github.add(commit(work, "release/notes.md", "- branch\n"), "success", 1);
  commit(main, "release/notes.md", "- dev\n");
  git(["merge", "-q", "--no-edit", "dev"]);
  fs.writeFileSync(path.join(work, "release/notes.md"), "- branch\n- dev\n");
  git(["commit", "-qam", "Merge dev"]);
  assert.equal(await check(false), null);
  assert.equal(github.writes.length, before + 1);
});
