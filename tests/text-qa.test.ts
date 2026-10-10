import assert from "node:assert/strict";
import test from "node:test";
import {
  qaActivity,
  qaPhase,
  qaStages,
} from "../app/src/features/guided/qaView.ts";

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
  // and lint finishes before screening is current.
  const screening = qa(
    {
      stage: "screen",
      screen: { accepted: 40, total: 100, lint: { accepted: 5, total: 5 } },
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
});
