import assert from "node:assert/strict";
import test from "node:test";
import {
  qaActivity,
  qaGroups,
  qaPhase,
  qaStages,
  qaStartOver,
  qaSummary,
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
      questions: [
        {
          id: "q",
          source: "",
          current: "",
          reason: "",
          places: 1,
          proposal: "",
        },
      ],
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
  // Lines an earlier QA reviewed, unchanged since, were context, not checked.
  assert.equal(
    qaSummary(
      qa(
        { stage: "complete", reviewed_before: { lines: 790 } },
        {
          applied: true,
          findings: [
            { id: "QA-0001", state: "applied" },
            { id: "QA-0002", state: "left-out" },
          ],
          coverage: { lines: 816, not_reviewed: 6 },
        },
      ),
    ),
    "1 correction applied · 1 left out · 20 lines checked · 790 unchanged since earlier QA",
  );
  // A correction apply left out leads its category, which shows its first
  // rows only, so a long task's summary count leads to it.
  const row = (id: string, family: string, state?: string) =>
    ({ id, family, category: "meaning", state }) as never;
  assert.deepEqual(
    qaGroups([
      row("QA-0001", "a", "applied"),
      row("QA-0002", "b", "left-out"),
    ])[0]!.findings.map((finding) => finding.id),
    ["QA-0002", "QA-0001"],
  );
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

test("Start over warns of an assistant still at work and offers to clear only results the playtest has", () => {
  const now = Date.parse("2026-11-09T12:00:00Z");
  const qa = (updated_at: string) =>
    ({
      task: "/qa/task",
      current: true,
      applied: false,
      message: "",
      findings: [
        { id: "a", state: "applied" },
        { id: "b", state: "undone" },
      ],
      questions: [{ id: "c", choice: "use", state: "applied" }],
      status: { stage: "screen" },
      updated_at,
    }) as never;
  const playtest = (report: string, problems: number) =>
    ({ report, problems: Array(problems).fill({}) }) as never;
  assert.deepEqual(
    qaStartOver(qa("2026-11-09T11:50:00Z"), playtest("r1", 2), now),
    { applied: 2, active: "2026-11-09T11:50:00Z", playtest: 2 },
  );
  // A review quiet for 15 minutes, and a playtest without a report, such
  // as one that never ran, ask nothing.
  assert.deepEqual(
    qaStartOver(qa("2026-11-09T11:45:00Z"), playtest("", 0), now),
    { applied: 2, active: "", playtest: null },
  );
  assert.equal(qaStartOver(qa(""), null, now).active, "");
  assert.equal(qaStartOver(qa(""), playtest("r1", 0), now).playtest, 0);
});
