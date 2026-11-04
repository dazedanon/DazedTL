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
      { fix: "f2", introduced: "old" },
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

test("review stats read only hashes from a trailer and skip a log line they can't read", () => {
  assert.deepEqual(
    namedFixes(
      "f1 abc1234 on dev\nf2\nf3 (def5678), 1234567890abcdef1234567890abcdef12345678\nf4 v2.61.0\n",
    ),
    [
      { fix: "f1", names: ["abc1234"] },
      {
        fix: "f3",
        names: ["def5678", "1234567890abcdef1234567890abcdef12345678"],
      },
      // Pointed out in the report rather than dropped.
      { fix: "f4", names: [] },
    ],
  );
  const independent = {
    reviewer: "independent",
    level: "high",
    head: "abc1234",
    findings: [{ summary: "Off by one", kind: "bug", outcome: "fixed" }],
  };
  const { landings, unread } = loggedLandings(
    [
      JSON.stringify({ range: "a..b", level: "high", findings: [] }),
      '{"range":"abc',
      JSON.stringify({ range: "b..c", ...independent }),
      JSON.stringify({ range: "c..d", ...independent, level: "low" }),
      "",
    ].join("\n"),
  );
  assert.deepEqual(landings, [
    { range: "a..b", reviews: 0, findings: [] },
    {
      range: "b..c",
      reviews: 1,
      findings: [
        { summary: "Off by one", kind: "bug", outcome: "fixed", review: 1 },
      ],
    },
  ]);
  assert.equal(unread.length, 2);
  assert.match(unread[0], /line 2 is not JSON/);
  assert.match(unread[1], /line 4: .*level/);
});
