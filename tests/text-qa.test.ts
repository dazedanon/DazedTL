import assert from "node:assert/strict";
import test from "node:test";
import {
  qaActivity,
  qaPhase,
  qaStages,
  qaUnsaved,
} from "../app/src/features/guided/qaView.ts";
import { changedWords } from "../app/src/ui/changedWords.ts";

test("the QA strip marks one current stage and the activity line reads the engine's counts", () => {
  const qa = (status: Record<string, unknown>, extra: object = {}) =>
    ({
      task: "/qa/task",
      current: true,
      applied: false,
      message: "",
      findings: [],
      questions: [],
      status,
      ...extra,
    }) as never;
  const marks = (value: never) =>
    qaStages(value).map((step) => `${step.label}:${step.state}`);
  // Deep review that opened while screening continues reads as started,
  // and lint finishes, with a proposal declined, before screening is current.
  const screening = qa(
    {
      stage: "screen",
      screen: {
        accepted: 40,
        total: 100,
        lint: { accepted: 4, total: 5, declined: 1 },
      },
      deep: { accepted: 3, total: 24 },
    },
    {
      activity: { stage: "screen", done: 40, total: 100, eta_seconds: 1500 },
    },
  );
  assert.deepEqual(marks(screening), [
    "Preflight:done",
    "Lint:done",
    "Screen:current",
    "Deep:started",
    "Consistency:next",
    "Editorial:next",
    "Apply:next",
  ]);
  assert.equal(
    qaActivity(screening),
    "Screening 40 of 100 · about 25 min left",
  );
  // A complete task waits only on the user's answers, then on apply.
  const asking = qa(
    { stage: "complete" },
    {
      questions: [{ id: "q", source: "", current: "", reason: "", places: 1 }],
    },
  );
  assert.equal(qaPhase(asking), "questions");
  assert.deepEqual(marks(asking).slice(-2), [
    "Editorial:done",
    "Apply:current",
  ]);
  assert.equal(
    qaPhase(qa({ stage: "complete" }, { applied: true, current: false })),
    "applied",
    "applying changes the text QA checked without making it outdated",
  );
  assert.equal(qaPhase(qa({ stage: "deep" }, { current: false })), "outdated");
  // An Apply again whose checkpoint failed leaves its correction applied and
  // nothing else to report the failure, so the page offers saving the version.
  const applied = qa(
    { stage: "complete" },
    { applied: true, findings: [{ id: "QA-0001", state: "applied" }] },
  );
  assert.ok(qaUnsaved(applied, { key: "qa-reapply:QA-0001", error: "failed" }));
  assert.ok(!qaUnsaved(applied, { key: "qa-undo:QA-0001", error: "failed" }));
});

test("an applied correction marks only the words it changed", () => {
  const marks = (before: string, after: string) => {
    const words = changedWords(before, after);
    const show = (side: typeof words.before) =>
      side.map((run) => (run.changed ? `[${run.text}]` : run.text)).join("");
    return [show(words.before), show(words.after)];
  };
  // Neighboring changed words join across the space between them, and the
  // marks keep to the words on a wrapped line.
  assert.deepEqual(
    marks("When\nhe touches me there...♥", "When\nyou touch me there...♥"),
    ["When\n[he touches] me there...♥", "When\n[you touch] me there...♥"],
  );
  // A space added inside a run of letters and digits is marked on its own.
  assert.deepEqual(marks("BanditLv2", "Bandit Lv2"), [
    "BanditLv2",
    "Bandit[ ]Lv2",
  ]);
  // A rewrite sharing only punctuation is left unmarked.
  assert.deepEqual(marks("The fox jumps.", "A cat sleeps."), [
    "The fox jumps.",
    "A cat sleeps.",
  ]);
});
