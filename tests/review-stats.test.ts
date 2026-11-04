import assert from "node:assert/strict";
import test from "node:test";
import { summarize } from "../scripts/review-stats.mjs";

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
        commits: ["c1", "c2"],
      },
    ],
    [
      { fix: "f1", introduced: "c2" },
      { fix: "f2", introduced: "old" },
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
  assert.deepEqual(summary.before, [{ fix: "f2", introduced: "old" }]);
});
