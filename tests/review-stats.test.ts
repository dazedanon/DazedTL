import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { commitFormat, readCommits } from "../scripts/fix-trailers.mjs";
import { gitIn } from "../scripts/land-lock.mjs";
import {
  codeLines,
  exposureDays,
  highEnd,
  loggedLandings,
  summarize,
} from "../scripts/review-stats.mjs";

const day = 86_400_000;
const now = 100 * day;
const old = now - exposureDays * day;

test("review stats put each escaped bug on the landing that let it in, once it is old enough", () => {
  const fix = (
    fix: string,
    introduced: string[],
    found: string | null = null,
    marks: string[] = [],
  ) => ({ fix, introduced, marks, found });
  const summary = summarize(
    [
      {
        range: "a..b",
        reviews: 0,
        findings: [],
        landed: old - day,
        commits: ["b1"],
        lines: 40,
      },
      {
        range: "b..c",
        reviews: 2,
        findings: [
          { kind: "bug", outcome: "fixed", review: 1 },
          { kind: "bug", outcome: "dismissed", review: 2 },
          { outcome: "fixed", review: 1 },
        ],
        landed: old,
        commits: ["c1", "c2", "c3"],
        lines: 1200,
      },
      // Too recent to count the bugs that got past it yet.
      {
        range: "c..d",
        reviews: 1,
        findings: [],
        landed: now - day,
        commits: ["d1", "d2"],
        lines: 150,
      },
      {
        range: "d..e",
        reviews: 1,
        findings: [],
        landed: null,
        commits: ["e1"],
        lines: 5,
      },
    ],
    [
      // One bug, however many of the landing's commits its fix names.
      fix("f1", ["c2", "c1", "oldest"], "user"),
      fix("f2", ["old", "older"]),
      // A bug its own landing fixed never got past that landing.
      fix("c3", ["c1"], "review"),
      fix("e1", ["d1"], "discord"),
      fix("u1", [], "user", ["unknown"]),
      fix("n1", [], "author", ["none"]),
    ],
    { now, fixCommits: new Set(["c3", "d1", "e1"]) },
  );
  assert.deepEqual(summary.byReviews, [
    [0, { landings: 1, escapes: 0 }],
    [2, { landings: 1, escapes: 1 }],
  ]);
  assert.deepEqual(summary.bySize, [
    ["under 100", { landings: 1, escapes: 0 }],
    ["1000 or more", { landings: 1, escapes: 1 }],
  ]);
  assert.equal(summary.recent, 2);
  assert.deepEqual(summary.rounds, [
    [
      1,
      {
        bug: { fixed: 1, dismissed: 0 },
        unsorted: { fixed: 1, dismissed: 0 },
      },
    ],
    [2, { bug: { fixed: 0, dismissed: 1 } }],
  ]);
  assert.deepEqual(
    summary.escaped.map(({ fix, introduced, range }) => [
      fix,
      introduced,
      range,
    ]),
    [
      ["f1", "c2", "b..c"],
      ["e1", "d1", "c..d"],
    ],
  );
  // e1's bug got past a landing too recent to count yet.
  assert.deepEqual(summary.foundBy, [["user", 1]]);
  // Got past b..c, so f1 is not also counted among the outside ones.
  assert.deepEqual(summary.outside, [{ fix: "f2", introduced: "old" }]);
  // One of five fixes naming where their bug came from says unknown.
  assert.deepEqual(summary.origins, {
    named: 4,
    unknown: 1,
    none: 1,
  });
  assert.equal(highEnd(4, summary.origins), 5);
  assert.equal(highEnd(0, { named: 0, unknown: 2 }), Infinity);
  // e1's bug came from d1, a fix another landing held.
  assert.deepEqual(summary.chains, [["e1", "d1"]]);
});

test("review stats list a chain of fixes across landings, and only those", () => {
  const landing = (range: string, commits: string[]) => ({
    range,
    reviews: 1,
    findings: [],
    landed: old,
    commits,
    lines: 10,
  });
  const fix = (fix: string, introduced: string[]) => ({
    fix,
    introduced,
    marks: [],
    found: null,
  });
  const { chains } = summarize(
    [
      landing("a..b", ["f1", "f1b"]),
      landing("b..c", ["f2"]),
      landing("c..d", ["f3"]),
    ],
    [
      fix("f3", ["f2", "feat"]),
      fix("f2", ["f1"]),
      // A review's catch within its own landing is no link.
      fix("f1b", ["f1"]),
      fix("f1", ["before"]),
    ],
    { now, fixCommits: new Set(["f1", "f1b", "f2", "f3"]) },
  );
  assert.deepEqual(chains, [["f3", "f2", "f1"]]);
});

test("review stats read real trailers by their first word, code lines from numstat, and skip a log line they can't read", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-stats-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  git(["init", "-q", "-b", "dev"]);
  git(["config", "user.name", "Test"]);
  git(["config", "user.email", "test@example.com"]);
  const commit = (message: string, ...trailers: string[]) => {
    fs.appendFileSync(path.join(dir, "code.mjs"), "x\n");
    git(["add", "-A"]);
    git([
      "commit",
      "-qm",
      message,
      ...(trailers.length ? ["-m", trailers.join("\n")] : []),
    ]);
    return git(["rev-parse", "HEAD"]).stdout.trim();
  };
  const sha256 = "a".repeat(64);
  commit("feat: base");
  commit(
    "fix: one",
    "Introduced-by: abc1234 defaced the cache",
    "Found-by: User, in chat",
  );
  commit(
    "fix: two",
    "Introduced-by: (def5678),",
    `Introduced-by: ${sha256}`,
    "Found-by: ci",
  );
  commit(
    "fix: three",
    "Introduced-by: Unknown",
    "Introduced-by: none",
    "Found-by: somebody",
  );
  commit("fix: four", "Introduced-by: v2.61.0", "Introduced-by: #1234567");
  // Not trailers: they are no final paragraph of their own.
  commit("fix: five\n\nIntroduced-by: abc1234\nsaid in the body");
  const read = readCommits(
    git(["log", `--format=${commitFormat}`, "dev"]).stdout,
  ).map(
    ({ commit, ...rest }) => (assert.match(commit, /^[0-9a-f]{40}$/), rest),
  );
  assert.deepEqual(read, [
    { subject: "fix: five", hashes: [], marks: [], found: [], unread: [] },
    {
      subject: "fix: four",
      hashes: [],
      marks: [],
      found: [],
      unread: [
        { key: "Introduced-by", value: "v2.61.0" },
        { key: "Introduced-by", value: "#1234567" },
      ],
    },
    {
      subject: "fix: three",
      hashes: [],
      marks: ["unknown", "none"],
      found: [],
      unread: [{ key: "Found-by", value: "somebody" }],
    },
    {
      subject: "fix: two",
      hashes: ["def5678", sha256],
      marks: [],
      found: ["ci"],
      unread: [],
    },
    {
      subject: "fix: one",
      hashes: ["abc1234"],
      marks: [],
      found: ["user"],
      unread: [],
    },
    { subject: "feat: base", hashes: [], marks: [], found: [], unread: [] },
  ]);

  const base = git(["rev-parse", "HEAD"]).stdout.trim();
  for (const [file, text] of [
    ["tests/a.test.ts", "1\n2\n"],
    ["docs/a.md", "1\n"],
    ["app/a.json", "1\n"],
    ["app/src/api/contracts.ts", "1\n"],
    ["image.png", "\0binary"],
  ]) {
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    fs.writeFileSync(path.join(dir, file), text);
  }
  fs.writeFileSync(path.join(dir, "code.mjs"), "y\n");
  git(["add", "-A"]);
  git(["commit", "-qm", "feat: more"]);
  // code.mjs: six lines removed, one added.
  assert.equal(
    codeLines(
      git(["diff", "--numstat", "--no-renames", "-z", `${base}..HEAD`]).stdout,
    ),
    7,
  );

  const { landings, unread } = loggedLandings(
    [
      JSON.stringify({
        landed: "2026-11-02T18:04:12.670Z",
        range: "a..b",
        findings: [{ summary: "Typo", outcome: "fixed" }],
      }),
      '{"range":"abc',
      JSON.stringify({
        range: "b..c",
        reviewer: "independent",
        reviews: 2,
        findings: [
          { kind: "bug", outcome: "fixed", review: 2 },
          { outcome: "dismissed" },
        ],
      }),
      JSON.stringify({ range: "c..d", findings: [{ summary: "No outcome" }] }),
      JSON.stringify({ range: "d..e", skipped: "Docs only" }),
      "",
    ].join("\n"),
  );
  assert.deepEqual(landings, [
    {
      range: "a..b",
      reviews: 0,
      findings: [{ outcome: "fixed", review: 0 }],
      landed: Date.parse("2026-11-02T18:04:12.670Z"),
    },
    {
      range: "b..c",
      reviews: 2,
      findings: [
        { kind: "bug", outcome: "fixed", review: 2 },
        { outcome: "dismissed", review: 1 },
      ],
      landed: null,
    },
    { range: "d..e", reviews: 0, findings: [], landed: null },
  ]);
  assert.equal(unread.length, 2);
  assert.match(unread[0], /line 2 is not JSON/);
  assert.match(
    unread[1],
    /line 4 has no range or a finding without an outcome/,
  );
});
