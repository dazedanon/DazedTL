import assert from "node:assert/strict";
import test from "node:test";
import type { GlossaryLine, GlossaryState } from "../app/src/api/contracts.ts";
import {
  glossaryGroups,
  glossaryPhase,
} from "../app/src/features/guided/glossaryView.ts";

const line = (
  key: string,
  terms: [string, number][],
  extra: Partial<GlossaryLine> = {},
): GlossaryLine => ({
  key,
  file: "Map001.json",
  pointer: "/events/1/pages/0/list/0/parameters/0",
  source: "",
  live: key,
  terms: terms.map(([source, start]) => ({
    source,
    english: source,
    start,
    end: start + 1,
  })),
  state: "open",
  ...extra,
});

test("lines with a proposal lead, and a line kept on this visit keeps its place", () => {
  const found = [
    line("bread", [["パン", 0]]),
    line("sonko", [["存子", 0]], { proposal: "Aruko" }),
    line("pray", [["祈り", 0]]),
    line("pray-kept", [["祈り", 0]], { state: "kept", choice: "keep" }),
    line("kept-now", [["回復", 0]], { state: "kept", choice: "keep" }),
    // The same terms in another order are the same group.
    line("both", [
      ["小町", 4],
      ["存子", 0],
    ]),
    line("both-again", [
      ["存子", 0],
      ["小町", 2],
    ]),
  ];
  const { proposed, unproposed, kept } = glossaryGroups(
    found,
    new Set(["kept-now"]),
  );
  assert.deepEqual(
    proposed.map((group) => group.lines.map((row) => row.key)),
    [["sonko"]],
  );
  assert.deepEqual(
    unproposed.map((group) => group.lines.map((row) => row.key)),
    [["both", "both-again"], ["bread"], ["pray"], ["kept-now"]],
  );
  assert.deepEqual(
    unproposed[0].terms.map((term) => term.source),
    ["存子", "小町"],
  );
  assert.deepEqual(
    kept.map((row) => row.key),
    ["pray-kept"],
  );
});

test("the check is done once a current scan leaves nothing to choose or apply", () => {
  const state = (extra: Partial<GlossaryState>): GlossaryState => ({
    scan: "scan",
    current: true,
    lines: 10,
    flagged: 2,
    open: 0,
    fixes: 0,
    kept: 2,
    revision: "r",
    ...extra,
  });
  assert.equal(glossaryPhase(state({ scan: null })), "none");
  assert.equal(glossaryPhase(state({ current: false })), "outdated");
  assert.equal(glossaryPhase(state({ open: 1 })), "review");
  assert.equal(glossaryPhase(state({ fixes: 1 })), "review");
  assert.equal(glossaryPhase(state({})), "done");
});
