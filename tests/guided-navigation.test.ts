import assert from "node:assert/strict";
import test from "node:test";
import type {
  GuidedState,
  Preview,
  ImageManagerState,
  TranslationState,
} from "../app/src/api/contracts.ts";
import {
  initialPosition,
  runPhase,
  runStage,
  stagesFor,
  taskForStage,
  unfinishedRun,
} from "../app/src/features/guided/workflow.ts";
import { guidedProgress } from "../app/src/features/guided/progress.ts";
import { reviewSignature } from "../app/src/features/guided/pending.ts";

test("saved runs choose their owning task instead of native progress labels", () => {
  const translation = {
    lifecycle: { source_backup: { available: true } },
    git: { configured: true },
  } as TranslationState;
  const state = {
    engine: "MVMZ",
    step: "setup",
    task: null,
    phase: "advanced",
    run: { mode: "batch", phase: "batch_approval", status: "waiting" },
  } as GuidedState;
  assert.equal(runPhase(state), "advanced");
  assert.deepEqual(initialPosition(state, translation), {
    step: "translate",
    task: "other-event-text",
  });
  state.run!.mode = "speakers";
  assert.deepEqual(initialPosition(state, translation), {
    step: "context",
    task: "run",
  });
  state.step = "context";
  state.task = "glossary";
  assert.deepEqual(initialPosition(state, translation), {
    step: "context",
    task: "guidance",
  });
  state.run!.mode = "translate";
  state.run!.phase = "complete";
  state.phase = "database";
  assert.equal(runPhase(state), "database");
  assert.equal(runStage(state), "translate");
  state.step = "translate";
  state.task = "dialogue";
  assert.deepEqual(initialPosition(state, translation), {
    step: "translate",
    task: "dialogue",
  });
  state.task = "database";
  assert.deepEqual(initialPosition(state, translation), {
    step: "translate",
    task: "database",
  });
  state.task = "variables";
  assert.deepEqual(initialPosition(state, translation), {
    step: "translate",
    task: "other-event-text",
  });
  state.run!.logicalPhase = "dialogue";
  state.phase = "advanced";
  assert.equal(runPhase(state), "dialogue");
  state.run!.status = "waiting";
  state.task = "main-text";
  assert.deepEqual(initialPosition(state, translation), {
    step: "translate",
    task: "dialogue",
  });
  for (const task of ["audit", "sources", "advanced-run", "variables"]) {
    state.step = "translate";
    state.task = task;
    assert.deepEqual(initialPosition(state, translation), {
      step: "translate",
      task: "other-event-text",
    });
  }
  assert.deepEqual(
    stagesFor("MVMZ")
      .find((stage) => stage.id === "translate")!
      .tasks.map((task) => task.id),
    ["database", "dialogue", "other-event-text", "plugins", "images"],
  );
  assert.deepEqual(
    stagesFor("ACE")
      .at(-1)!
      .tasks.map((task) => task.id),
    ["package"],
  );
  // Five stages: Plugin files and Images are Translate tasks, and Check
  // holds the line width check and Text QA.
  assert.deepEqual(
    stagesFor("MVMZ").map((stage) => stage.id),
    ["setup", "context", "translate", "check", "release"],
  );
  for (const task of ["plugins", "images"]) {
    state.step = "translate";
    state.task = task;
    assert.deepEqual(initialPosition(state, translation), {
      step: "translate",
      task,
    });
  }
  for (const task of ["fitting", "qa"]) {
    state.step = "check";
    state.task = task;
    assert.deepEqual(initialPosition(state, translation), {
      step: "check",
      task,
    });
  }
  for (const status of [
    "failed",
    "stopped",
    "interrupted",
    "running",
    "waiting",
  ]) {
    state.run!.status = status;
    assert.equal(unfinishedRun(state), ["running", "waiting"].includes(status));
  }
  for (const status of ["complete", "canceled"]) {
    state.run!.status = status;
    assert.equal(unfinishedRun(state), false);
  }
});

test("phase navigation restores an available task and falls back for removed or differently owned tasks", () => {
  const state = {
    engine: "MVMZ",
    positions: { context: "speakers", setup: "extract", translate: "run" },
    run: { mode: "translate" },
  } as GuidedState;
  const stages = stagesFor(state.engine);
  const context = stages.find((stage) => stage.id === "context")!;
  assert.equal(taskForStage(state, context), "speakers");
  // A task setup no longer has opens setup's one task.
  assert.equal(taskForStage(state, stages[0]), "setup");
  assert.equal(
    taskForStage(
      state,
      stages.find((stage) => stage.id === "translate")!,
    ),
    "database",
  );
  state.positions.translate = "main-text";
  state.phase = "dialogue";
  assert.equal(
    taskForStage(
      state,
      stages.find((stage) => stage.id === "translate")!,
    ),
    "dialogue",
  );
  state.positions.context = "no-longer-available";
  assert.equal(taskForStage(state, context), "names");
  state.positions.context = "run";
  assert.equal(taskForStage(state, context), "names");
  state.run!.mode = "speakers";
  assert.equal(taskForStage(state, context), "run");
  state.run = null;
  assert.equal(taskForStage(state, context), "names");
  state.positions = {};
  assert.equal(taskForStage(state, context), "names");
  state.step = "context";
  state.task = "no-longer-available";
  assert.deepEqual(
    initialPosition(state, { lifecycle: {}, git: {} } as TranslationState),
    { step: "setup", task: "setup" },
  );
  assert.deepEqual(
    initialPosition(state, {
      lifecycle: { source_backup: { available: true } },
    } as TranslationState),
    { step: "context", task: "names" },
  );
});

test("the Project page continues with the next step and keeps a later saved position", () => {
  const translation = {
    lifecycle: { source_backup: { available: true } },
    git: { configured: false },
  } as TranslationState;
  const state = {
    projectId: "game",
    engine: "MVMZ",
    step: "setup",
    task: "backup",
    preferences: { values: { selected: [], engine_options: {} } },
    files: [],
    runs: [],
    phaseRuns: {},
    readiness: { outputs: [], applied: [], layout_scan: null },
    comparisons: { status: "not_needed" },
    eventText: {
      status: "missing",
      applied: false,
      enabled: [],
      rows: [{ key: "CODE356" }],
    },
    contextSetup: { documents: {}, layoutStatus: "missing" },
    speakerSetup: {},
    speakerScan: {},
    preparation: { complete: false },
    artifacts: [],
    operations: [],
  } as unknown as GuidedState;
  // An unfinished setup is the next step, even from a task it no longer
  // has, and needs no separate way back.
  let progress = guidedProgress(state, translation);
  assert.equal(progress.next?.task, "setup");
  assert.equal(progress.last, null);
  // A finished setup has nothing to return to, so Continue opens the next task.
  translation.git!.configured = true;
  state.task = "setup";
  progress = guidedProgress(state, translation);
  assert.equal(progress.next?.task, "names");
  assert.equal(progress.last, null);
  // A later saved position stays reachable beside the next step.
  state.step = "check";
  state.task = "fitting";
  progress = guidedProgress(state, translation);
  assert.equal(progress.next?.task, "names");
  assert.equal(progress.last?.task, "fitting");
  // Images finishes once every image in its list is in the game: an edited
  // image in the list that changed after the assistant's check keeps it open.
  state.artifacts = [{ current: true }] as GuidedState["artifacts"];
  const images = {
    projectId: state.projectId,
    discovery: { status: "complete" },
    editing: { status: "complete" },
    counts: {
      examined: 2,
      applied: 1,
      recommended: 1,
      uncertain: 0,
      selected: 2,
      selectedApplied: 1,
      selectedNeedsReview: 1,
    },
  } as unknown as ImageManagerState;
  const finished = () =>
    guidedProgress(state, translation, { images }).stages.flatMap((stage) =>
      stage.tasks.filter((task) => task.done).map((task) => task.id),
    );
  assert.deepEqual(finished(), ["setup", "package"]);
  Object.assign(images.counts, { selected: 1, selectedNeedsReview: 0 });
  assert.deepEqual(finished(), ["setup", "images", "package"]);
  // An investigation that leaves nothing to translate closes Images, until
  // a later investigation waits on the assistant, and Other event text closes
  // once current findings are applied with no source enabled.
  Object.assign(images.counts, {
    applied: 0,
    recommended: 0,
    selected: 0,
    selectedApplied: 0,
  });
  images.discovery.status = "awaiting_results";
  assert.deepEqual(finished(), ["setup", "package"]);
  images.discovery.status = "complete";
  state.eventText.status = "ready";
  assert.deepEqual(finished(), ["setup", "images", "package"]);
  state.eventText.applied = true;
  assert.deepEqual(finished(), [
    "setup",
    "other-event-text",
    "images",
    "package",
  ]);
  // A source turned on since the findings were applied reopens the task.
  state.preferences.values.engine_options.CODE356 = true;
  assert.deepEqual(finished(), ["setup", "images", "package"]);
});

test("a text review re-checked before Apply notices changes past the visible diff", () => {
  const preview = (after: string) =>
    ({
      action: "export_selected",
      paths: ["Map038.json"],
      // A large file's diff is cut off, so both reviews show the same text.
      publication: [
        {
          path: "data/Map038.json",
          before: "b",
          after,
          diff: "@@ first 16,000 characters",
        },
      ],
    }) as unknown as Preview;
  assert.notEqual(
    reviewSignature(preview("reviewed")),
    reviewSignature(preview("changed later")),
  );
});
