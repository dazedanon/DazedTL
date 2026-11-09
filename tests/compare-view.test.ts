import assert from "node:assert/strict";
import test from "node:test";
import type {
  CompareModel,
  Comparison,
  WorkspaceSnapshot,
} from "../app/src/api/contracts.ts";
import {
  actionFeedback,
  actionKey,
  blindOrder,
  columnError,
  columnSummary,
  compareInputs,
  compareOffered,
  comparisonText,
  current,
  estimateTotal,
  glossaryChanges,
  isComparison,
  keptRequests,
  leftOut,
  modelDetail,
  namesHidden,
  nextStep,
  picks,
  recordedMarks,
  reportsRun,
  Rereads,
  runningComparison,
  runningStatus,
  runStatus,
  runStep,
  shownKey,
  shownOperation,
} from "../app/src/features/compare/compareView.ts";

const model = (index: number, extra: Partial<CompareModel> = {}) =>
  ({
    index,
    connection: "Stand-in",
    model: `model-${index}`,
    choice: { connection_id: "local", model: `model-${index}` },
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
  const sent = { connection_id: "local", model: "model-0", effort: null };
  const tune = comparison({
    kind: "tune",
    candidates: [model(0, { choice: { ...sent, effort: "low" } })],
  });
  const tuned = { ...choices, kind: "tune" as const, candidates: [sent] };
  assert.equal(current([tune], tuned).latest, undefined);
  // The default effort reads as the backend keeps it, left out.
  assert.equal(
    current([comparison({ kind: "tune", candidates: [model(0)] })], tuned)
      .latest?.kind,
    "tune",
  );
  // After Keep this test's, an estimate of the glossary as edited from the
  // revision before a Context save offered Translate, which was refused.
  const edited = { ...sent, glossary: "勇者 (Hero)", glossary_revision: "r1" };
  const before = comparison({
    kind: "tune",
    candidates: [model(0, { choice: edited })],
  });
  assert.equal(
    current([before], {
      ...tuned,
      candidates: [{ ...edited, glossary_revision: "r2" }],
    }).latest,
    undefined,
  );
  assert.equal(
    current([before], { ...tuned, candidates: [edited] }).latest,
    before,
  );
});

test("a footer's refusal shows only for the choices it ran with, and a start stays busy through any edit", () => {
  // Reset and other lines left a refusal under an enabled Estimate cost.
  const refused = {
    busy: false,
    key: actionKey("estimate", choices),
    error: "Refused.",
  };
  assert.deepEqual(actionFeedback(refused, "estimate", choices), {
    pending: false,
    error: "Refused.",
  });
  assert.equal(
    actionFeedback(refused, "estimate", { ...choices, lines: 25 }).error,
    "",
  );
  assert.equal(
    actionFeedback(refused, "estimate", {
      ...choices,
      candidates: choices.candidates.slice(0, 1),
    }).error,
    "",
  );
  assert.equal(actionFeedback(refused, "translate", choices).error, "");
  // Use these settings while an estimate started cleared it, so Estimate
  // again looked ready while a click did nothing.
  const starting = { ...refused, busy: true, error: "" };
  assert.equal(
    actionFeedback(starting, "estimate", { ...choices, lines: 25 }).pending,
    true,
  );
  assert.equal(actionFeedback(starting, "translate", choices).pending, false);
  assert.deepEqual(
    actionFeedback({ busy: false, key: "", error: "" }, "estimate", choices),
    { pending: false, error: "" },
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

test("a method change, a loaded Manual file, a new Assistant-led run, Start over and a Context save read the comparisons again", () => {
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
    glossary = "g1",
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
        documents: {
          glossary: { revision: glossary },
          game: { revision: "c1" },
        },
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
    // Tune notices a glossary saved in Context, which Use then asks about.
    observed({ glossary: "g2" }),
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

test("a model's price under its name keeps tenths of a second for a short run", () => {
  assert.equal(
    modelDetail(model(0, { cost: 0.002, seconds: 0.4 }), true),
    "$0.002 · 0.4 s",
  );
  assert.equal(
    modelDetail(model(0, { cost: 0.002, seconds: 3.4 }), true),
    "$0.002 · 3.4 s",
  );
  assert.equal(
    modelDetail(model(0, { cost: 0.002, seconds: 72 }), true),
    "$0.002 · 1 min 12 s",
  );
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
  // Its message names the model it is at, which a blind comparison hides,
  // so every page that shows it, the Guided operation row too, says this.
  assert.equal(running!.text, "Translating a comparison");
  assert.equal(comparisonText("compare_estimate"), "Estimating a comparison");
  assert.equal(isComparison("translate"), false);
  // The Guided operation row read "Running stand-in-b · preparing".
  assert.equal(
    shownOperation(operation("running")).message,
    "a comparison on Compare models",
  );
  const other = { action: "translate", message: "Map001 · 2 of 6" };
  assert.equal(shownOperation(other), other);
  // The app runs one at a time, so every game's work waits, not this one's.
  assert.doesNotMatch(running!.waits, /this game/);
  assert.equal(runningComparison([operation("stopped")]), null);
  // A game whose folder went missing keeps Compare, where alone it stops,
  // while its comparison runs.
  const snapshot = (operations: unknown[]) =>
    ({
      application: { project: { id: "p" } },
      compareOperations: operations,
    }) as unknown as WorkspaceSnapshot;
  const missing = { id: "p", available: false };
  assert.equal(compareOffered(missing, snapshot([operation("running")])), true);
  assert.equal(
    compareOffered(missing, snapshot([operation("stopped")])),
    false,
  );
  assert.equal(
    compareOffered({ ...missing, id: "q" }, snapshot([operation("running")])),
    false,
  );
  // A run that ended unfinished shows beside Estimate again; while one
  // runs, the footer's status line says so instead.
  const stopped = comparison({ stage: "translation", status: "stopped" });
  assert.equal(reportsRun(stopped), true);
  assert.equal(reportsRun({ ...stopped, status: "running" }), false);
  assert.equal(reportsRun({ ...stopped, status: "complete" }), false);
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

test("a blind comparison hides its names while its lines come in, until revealed or every line is picked", () => {
  const running = comparison({
    stage: "translation",
    translationId: "run",
    status: "running",
    blind: true,
  });
  assert.equal(namesHidden(running, undefined, false), true);
  // Picks saved here lead the read, which may not hold them yet.
  assert.equal(
    namesHidden(
      { ...running, blind: false },
      { blind: true, revealed: false },
      false,
    ),
    true,
  );
  assert.equal(
    namesHidden(running, { blind: true, revealed: true }, false),
    false,
  );
  assert.equal(namesHidden(running, undefined, true), false);
  // Not translated yet: the names are the user's own choices.
  assert.equal(
    namesHidden(comparison({ blind: true }), undefined, false),
    false,
  );
});

test("Reveal now and unticking Blind act on a translation that is still running", () => {
  // Picks waited for the translation to end, so Reveal now did nothing and
  // unticking Blind showed names in the footer while the columns hid them.
  const running = comparison({
    stage: "translation",
    translationId: "run",
    status: "running",
    blind: true,
  });
  const read = recordedMarks(running, {});
  assert.deepEqual(read, { marks: {}, blind: true, revealed: false });
  for (const change of [{ revealed: true }, { blind: false }]) {
    const saved = { run: { ...read!, ...change } };
    assert.equal(
      namesHidden(running, recordedMarks(running, saved) ?? undefined, false),
      false,
    );
  }
  assert.equal(recordedMarks(comparison({}), {}), null);
});

test("a hidden model's error leaves out its words, which may name it", () => {
  const failed = model(0, { error: "Error from provider for GPT-4o mini" });
  assert.doesNotMatch(columnError(failed, true) ?? "", /GPT/);
  assert.equal(columnError(failed, false), failed.error);
  assert.equal(columnError(model(0), true), undefined);
});

test("a running comparison shows as one status line saying what it does, without names", () => {
  // The footer showed Stop, a "Running" spinner and a disabled Estimate
  // cost with its own spinner, all for one run.
  const rows = [1, 2, 3].map((id) => ({
    id: String(id),
    speaker: "",
    source: "はい",
    translations: [],
    problems: [],
  }));
  const priced = { estimate: { cost: 0.01, requests: 1 } };
  const estimated = comparison({
    rows,
    candidates: [
      model(0, priced),
      model(1, { reused: true }),
      model(2, { error: "No price" }),
    ],
  });
  // A translation sends only what it neither reuses nor left out.
  assert.equal(
    runningStatus("compare_translate", estimated),
    "Translating 3 lines with 1 model…",
  );
  assert.equal(
    runningStatus("compare_estimate", comparison({ rows: [] })),
    "Estimating the lines with 2 models…",
  );
  assert.equal(
    runningStatus("compare_translate", undefined),
    "Translating an earlier set of models…",
  );
  assert.equal(
    runningStatus(
      "compare_translate",
      comparison({ rows, candidates: [model(0, { reused: true })] }),
    ),
    "Bringing back the earlier lines…",
  );
  assert.doesNotMatch(runningStatus("compare_translate", estimated), /model-/);
});

test("after a translation the one primary is Use, once there is a model to use", () => {
  const done = (models: CompareModel[], status = "complete") =>
    comparison({
      stage: "translation",
      translationId: "t",
      status,
      candidates: models,
    });
  const finished = { finished: true, cost: 0.01 };
  // One column: Use this model once it finished.
  const one = done([model(0, finished)]);
  assert.equal(nextStep(one, null).use?.label, "Use this model");
  assert.equal(nextStep(one, null).again, false);
  // Several: nothing while picking, Use most picked once every line is
  // picked and one leads, nothing on a tie.
  const two = done([model(0, finished), model(1, finished)]);
  const score = (picked: number, winner: number | null) => ({
    won: [1, 0],
    picked,
    total: 2,
    winner,
    tied: winner === null ? [0, 1] : [],
  });
  assert.equal(nextStep(two, score(1, 0)).use, null);
  assert.equal(nextStep(two, score(2, 0)).use?.label, "Use most picked");
  assert.equal(nextStep(two, score(2, null)).use, null);
  // A model that failed or stopped offers Estimate again, which reuses the
  // rest; one left out for no price doesn't.
  const failed = done([
    model(0, finished),
    model(1, { error: "Failed.", cost: 0 }),
  ]);
  assert.equal(nextStep(failed, score(2, 0)).again, true);
  const left = done([model(0, finished), model(1, { error: "No price" })]);
  assert.equal(nextStep(left, null).again, false);
  assert.equal(nextStep(done([model(0, finished)], "running"), null).use, null);
});

test("a model left out before anything was sent reads as left out, a warning", () => {
  const left = model(0, { error: "No price is available for this model." });
  assert.equal(leftOut(left), true);
  assert.match(columnError(left, true) ?? "", /^Left out/);
  assert.equal(leftOut(model(1, { error: "Failed.", cost: 0.01 })), false);
  assert.equal(
    leftOut(model(2, { error: "x", estimate: { cost: 0.01, requests: 1 } })),
    false,
  );
});

test("a reused model goes along at no cost and says so", () => {
  const estimated = comparison({
    candidates: [
      model(0, { estimate: { cost: 0.02, requests: 1 } }),
      model(1, { reused: true }),
    ],
  });
  const { cost, priced, sent, left } = estimateTotal(estimated);
  assert.deepEqual(
    { cost, priced, sent, left },
    {
      cost: 0.02,
      priced: 2,
      sent: 1,
      left: [],
    },
  );
  assert.equal(
    modelDetail(model(1, { reused: true }), false),
    "Reused, no new cost",
  );
  assert.equal(
    modelDetail(model(1, { reused: true, cost: 0.019, seconds: 6.2 }), true),
    "$0.019 · 6.2 s · reused",
  );
});

test("a column's settings read as the game's or what changed", () => {
  const choice = { connection_id: "c", model: "m" };
  assert.equal(columnSummary(choice), "Game’s settings");
  assert.equal(
    columnSummary({ ...choice, effort: "high", instruction: "Be old." }),
    "High effort · instruction",
  );
  assert.equal(
    columnSummary({ ...choice, glossary: "a", glossary_revision: "r" }),
    "Test glossary",
  );
  assert.equal(columnSummary({ ...choice, effort: null }), "Default effort");
});
