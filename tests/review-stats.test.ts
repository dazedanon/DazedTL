import assert from "node:assert/strict";
import test from "node:test";
import {
  loggedLandings,
  namedFixes,
  summarize,
} from "../scripts/review-stats.mjs";

test("review stats put each escaped bug on the landing that let it in", () => {
  const summary = summarize(
    [
      { range: "a..b", reviews: 0, findings: [], commits: ["b1"] },
      {
        range: "b..c",
        reviews: 2,
        findings: [
          { kind: "bug", outcome: "fixed", review: 1 },
          { kind: "bug", outcome: "dismissed", review: 2 },
          { outcome: "fixed", review: 1 },
        ],
        commits: ["c1", "c2", "c3"],
      },
    ],
    [
      { fix: "f1", introduced: "c2" },
      // One bug, however many of the landing's commits its fix names.
      { fix: "f1", introduced: "c1" },
      { fix: "f2", introduced: "old" },
      { fix: "f2", introduced: "older" },
      // Got past b..c, so not also counted among the outside ones.
      { fix: "f1", introduced: "oldest" },
      // A bug its own landing fixed never got past that landing.
      { fix: "c3", introduced: "c1" },
    ],
  );
  assert.deepEqual(summary.byReviews, [
    [0, { landings: 1, escapes: 0 }],
    [2, { landings: 1, escapes: 1 }],
  ]);
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
  assert.deepEqual(summary.escaped, [
    { fix: "f1", introduced: "c2", range: "b..c", reviews: 2 },
  ]);
  assert.deepEqual(summary.outside, [{ fix: "f2", introduced: "old" }]);
});

test("review stats read each trailer's hash alone and skip a log line they can't read", () => {
  const sha256 = "a".repeat(64);
  const trailers = (...values: string[]) => values.join("\x1e");
  assert.deepEqual(
    namedFixes(
      [
        `f1\x1f${trailers("abc1234 defaced the cache")}`,
        "f2\x1f",
        `f3\x1f${trailers("(def5678),", sha256)}`,
        `f4\x1f${trailers("v2.61.0", "#1234567")}`,
      ].join("\n"),
    ),
    [
      { fix: "f1", names: ["abc1234"], unnamed: [] },
      { fix: "f3", names: ["def5678", sha256], unnamed: [] },
      { fix: "f4", names: [], unnamed: ["v2.61.0", "#1234567"] },
    ],
  );
  const { landings, unread } = loggedLandings(
    [
      JSON.stringify({
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
    { range: "a..b", reviews: 0, findings: [{ outcome: "fixed", review: 0 }] },
    {
      range: "b..c",
      reviews: 2,
      findings: [
        { kind: "bug", outcome: "fixed", review: 2 },
        { outcome: "dismissed", review: 1 },
      ],
    },
    { range: "d..e", reviews: 0, findings: [] },
  ]);
  assert.equal(unread.length, 2);
  assert.match(unread[0], /line 2 is not JSON/);
  assert.match(
    unread[1],
    /line 4 has no range or a finding without an outcome/,
  );
});
