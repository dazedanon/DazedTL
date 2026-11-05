import assert from "node:assert/strict";
import test from "node:test";
import type {
  CompareModel,
  Comparison,
  WorkspaceSnapshot,
} from "../app/src/api/contracts.ts";
import {
  blindOrder,
  compareInputs,
  current,
  estimateTotal,
  finishedModel,
  glossaryChanges,
  keptRequests,
  picks,
  Rereads,
  runningComparison,
  runStatus,
  runStep,
  shownKey,
} from "../app/src/features/compare/compareView.ts";

const model = (index: number, extra: Partial<CompareModel> = {}) =>
  ({
    index,
    connection: "Stand-in",
    connectionId: "local",
    model: `model-${index}`,
    ...extra,
  }) satisfies CompareModel;

const comparison = (extra: Partial<Comparison>): Comparison => ({
  id: "estimate-1",
  translationId: null,
  kind: "versus",
  file: "Map001.json",
  lines: 10,
  created: "2026-11-04T10:00:00Z",
  stage: "estimate",
  status: "complete",
  message: "",
  candidates: [model(0), model(1)],
  rows: [],
  marks: {},
  blind: false,
  revealed: false,
  ...extra,
});

const choices = {
  kind: "versus" as const,
  file: "Map001.json",
  lines: 10,
  candidates: [
    { connection_id: "local", model: "model-0" },
    { connection_id: "local", model: "model-1" },
  ],
};

test("a new estimate of the same choices acts next while the last translation stays in view", () => {
  const translated = comparison({
    id: "old",
    translationId: "old-run",
    stage: "translation",
  });
  const fresh = comparison({ id: "new" });
  const other = comparison({ id: "other", lines: 25 });
  const { latest, shown } = current([other, fresh, translated], choices);
  assert.equal(latest?.id, "new");
  assert.equal(shown?.id, "old");
  // A Tune test with a changed effort is not the run without one.
  const tune = comparison({
    kind: "tune",
    candidates: [model(0, { effort: "low" })],
  });
  assert.equal(
    current([tune], {
      ...choices,
      kind: "tune",
      candidates: [{ connection_id: "local", model: "model-0", effort: null }],
    }).latest,
    undefined,
  );
});

test("Translate's price leaves out the models an estimate couldn't price", () => {
  const total = estimateTotal(
    comparison({
      candidates: [
        model(0, { estimate: { cost: 0.004, requests: 1 } }),
        model(1, { error: "No price is available for this model." }),
        model(2, { estimate: { cost: 0.011, requests: 2 } }),
      ],
    }),
  );
  assert.equal(total.cost.toFixed(3), "0.015");
  assert.deepEqual(
    total.left.map((item) => item.model),
    ["model-1"],
  );
});

test("a blind order is shuffled once per comparison and stays the same", () => {
  const orders = ["a", "b", "c", "d", "e", "f"].map((id) => blindOrder(id, 4));
  for (const order of orders) assert.deepEqual([...order].sort(), [0, 1, 2, 3]);
  assert.deepEqual(blindOrder("a", 4), orders[0]);
  assert.ok(orders.some((order) => order.join() !== "0,1,2,3"));
});

test("picks count only translated rows, and a tie names no winner", () => {
  const row = (id: string, translated: boolean) => ({
    id,
    speaker: "",
    source: "よく来たな",
    translations: translated
      ? [
          { speaker: "", text: "Welcome." },
          { speaker: "", text: "Hello." },
        ]
      : [null, null],
    problems: [[], []],
  });
  const value = comparison({
    rows: [row("1", true), row("2", true), row("3", false)],
  });
  assert.deepEqual(picks(value, { "1": 1 }), {
    won: [0, 1],
    picked: 1,
    total: 2,
    winner: 1,
    tied: [],
  });
  const tied = picks(value, { "1": 0, "2": 1, "3": 0 });
  assert.equal(tied.picked, 2);
  assert.equal(tied.winner, null);
  assert.deepEqual(tied.tied, [0, 1]);
});

test("an edited glossary entry counts once, not as a removal and an addition", () => {
  const game = "# Places\nはじまりの村 (Starting Village)\n森 (Forest)\n";
  assert.equal(
    glossaryChanges(
      game,
      "# Places\nはじまりの村 (Village of Beginnings)\n森 (Forest)\n",
    ),
    1,
  );
  assert.equal(glossaryChanges(game, game + "祠 (Shrine)\n剣 (Sword)\n"), 2);
});

test("a method change, a loaded Manual file, a new Assistant-led run and Start over read the comparisons again", () => {
  const job = (id: string, created: string, kind = "translation") => ({
    id,
    kind,
    created,
  });
  const observed = ({
    method = "len",
    file = "",
    jobs = [job("run-1", "2026-11-04T10:00:00Z")],
    startedOver = "",
    progress = 0,
  } = {}) =>
    ({
      application: {
        project: { id: "p", method, source: "/games/a" },
      },
      guided: null,
      translation: {
        projectId: "p",
        jobs,
        manual: file ? { loaded: { sha256: file, loaded: "now" } } : null,
        lifecycle: {
          version: 1,
          ...(startedOver && { started_over: { at: startedOver } }),
        },
        progress: { done: progress },
      },
    }) as unknown as WorkspaceSnapshot;
  const before = compareInputs(observed(), "p");
  for (const changed of [
    observed({ method: "manual" }),
    observed({ file: "abc" }),
    observed({
      jobs: [
        job("run-1", "2026-11-04T10:00:00Z"),
        job("run-2", "2026-11-05T10:00:00Z"),
      ],
    }),
    observed({ startedOver: "2026-11-05T10:00:00Z" }),
  ])
    assert.notEqual(compareInputs(changed, "p"), before);
  // Progress and operations alone leave the lines as they were.
  assert.equal(compareInputs(observed({ progress: 5 }), "p"), before);
  assert.equal(
    compareInputs(
      observed({
        jobs: [
          job("run-1", "2026-11-04T10:00:00Z"),
          job("op", "2026-11-05T10:00:00Z", "operation"),
        ],
      }),
      "p",
    ),
    before,
  );
  assert.notEqual(
    compareInputs(observed({ file: "abc" }), "p"),
    compareInputs(observed({ file: "def" }), "p"),
  );
});

test("a hidden page keeps its last read key and reads once when shown after a change", () => {
  // Never shown, it reads nothing.
  assert.equal(shownKey(false, "settings:0", null), null);
  assert.equal(shownKey(true, "settings:0", null), "settings:0");
  // Settings saved while hidden start no read until the page shows.
  assert.equal(shownKey(false, "settings:2", "settings:0"), "settings:0");
  assert.equal(shownKey(true, "settings:2", "settings:0"), "settings:2");
});

test("the footer offers Translate for an unused priced estimate and Estimate again when none priced or once used", () => {
  const priced = comparison({
    candidates: [
      model(0, { estimate: { cost: 0.01 } as CompareModel["estimate"] }),
      model(1, { error: "No price" }),
    ],
  });
  assert.deepEqual(runStep(priced, priced), {
    step: "translate",
    cost: 0.01,
    left: ["model-1"],
  });
  // No model priced: estimating again is the way on, with why.
  const none = comparison({
    candidates: [model(0, { error: "No price" }), model(1, { error: "x" })],
  });
  const step = runStep(none, none);
  assert.equal(step.step, "estimate");
  assert.ok(step.step === "estimate" && step.again && step.reason);
  // Used: the saved comparison holds its translation, running then done.
  const used = comparison({
    ...priced,
    translationId: "run",
    stage: "translation",
    status: "running",
  });
  assert.equal(runStep(used, used).step, "translating");
  const done = { ...used, status: "complete" };
  assert.deepEqual(runStep(done, done), {
    step: "estimate",
    again: true,
    reason: "",
  });
});

test("an action on the comparisons waits for a read asked after it", async () => {
  const rereads = new Rereads();
  const ended: number[] = [];
  const first = rereads.ask();
  const second = rereads.ask();
  void first.done.then(() => ended.push(first.after));
  void second.done.then(() => ended.push(second.after));
  // A read asked before the action does not end its wait.
  rereads.settled(first.after);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(ended, [1]);
  rereads.settled(second.after);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(ended, [1, 2]);
});

test("Show request pages over the requests kept and says when fewer were kept than sent", () => {
  assert.deepEqual(keptRequests(model(0, { requests: 3, keptRequests: 3 })), {
    kept: 3,
    note: "",
  });
  const many = keptRequests(model(0, { requests: 45, keptRequests: 20 }));
  assert.equal(many.kept, 20);
  assert.match(many.note, /first 20 of its 45/);
  // A model that kept none has nothing to open.
  assert.equal(keptRequests(model(0, { requests: 2 })).kept, 0);
});

test("a model that failed or was stopped keeps its cost but is not offered for use", () => {
  const translated = (extra: Partial<CompareModel>, status = "complete") => {
    const item = comparison({
      translationId: "run",
      stage: "translation",
      status,
      candidates: [model(0, extra)],
    });
    return finishedModel(item, item.candidates[0]);
  };
  assert.equal(translated({ cost: 0.01, seconds: 3 }), true);
  assert.equal(
    translated(
      { cost: 0.004, error: "Stopped before it finished." },
      "stopped",
    ),
    false,
  );
  assert.equal(translated({ cost: 0.002, error: "HTTP 500" }), false);
  // Still running: its cost so far is no finished translation.
  assert.equal(translated({ cost: 0.001 }, "running"), false);
});

test("the comparison running for the game shows whatever the tab, until it ends", () => {
  const operation = (status: string, extra = {}) => ({
    id: "op",
    action: "compare_translate" as const,
    label: "Compare models",
    status,
    message: "stand-in · 2 of 6 lines",
    stopping: false,
    ...extra,
  });
  const running = runningComparison([
    operation("complete"),
    operation("running"),
  ]);
  assert.equal(running?.operation.status, "running");
  // Its message names the model it is at, which a blind comparison hides.
  assert.equal(running!.text, "Translating a comparison");
  assert.match(running!.waits, /waits/);
  assert.equal(runningComparison([operation("stopped")]), null);
});

test("the footer's run status keeps hidden names hidden and a stop short", () => {
  const item = (status: string) =>
    comparison({
      stage: "translation",
      translationId: "run",
      status,
      message: "stand-in · 2 of 6 lines",
    });
  assert.equal(
    runStatus(item("running"), "Translation", false).message,
    "stand-in · 2 of 6 lines",
  );
  assert.equal(runStatus(item("running"), "Translation", true).message, "");
  // Each model's column says what a stop kept.
  assert.deepEqual(runStatus(item("stopped"), "Translation", false), {
    label: "Translation",
    status: "stopped",
    message: "",
  });
  assert.equal(
    runStatus(item("failed"), "Translation", false).message,
    "stand-in · 2 of 6 lines",
  );
});
