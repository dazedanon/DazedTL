import assert from "node:assert/strict";
import test from "node:test";
import type {
  GuidedState,
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

test("saved runs choose their owning task instead of obsolete Prepare or native progress labels", () => {
  const translation = {
    lifecycle: { source_backup: { available: true } },
    git: { configured: true },
  } as TranslationState;
  const state = {
    engine: "MVMZ",
    step: "prepare",
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
    state.step = "advanced";
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
    ["database", "dialogue", "other-event-text"],
  );
  assert.deepEqual(
    stagesFor("ACE")
      .at(-1)!
      .tasks.map((task) => task.id),
    ["package"],
  );
  state.step = "apply";
  state.task = "plugins";
  assert.deepEqual(initialPosition(state, translation), {
    step: "plugins",
    task: "plugins",
  });
  state.task = "image-manager";
  assert.deepEqual(initialPosition(state, translation), {
    step: "images",
    task: "images",
  });
  state.step = "images";
  state.task = "images";
  assert.deepEqual(initialPosition(state, translation), {
    step: "images",
    task: "images",
  });
  for (const task of ["fitting", "playtest", "qa", "tools"]) {
    state.task = task;
    assert.deepEqual(initialPosition(state, translation), {
      step: "apply",
      task: "apply",
    });
  }
  assert.equal(
    stagesFor("MVMZ").findIndex((stage) => stage.id === "images"),
    stagesFor("MVMZ").findIndex((stage) => stage.id === "plugins") + 1,
  );
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
    positions: { context: "speakers", prepare: "extract", translate: "run" },
    run: { mode: "translate" },
  } as GuidedState;
  const stages = stagesFor(state.engine);
  const context = stages.find((stage) => stage.id === "context")!;
  assert.equal(taskForStage(state, context), "speakers");
  assert.equal(taskForStage(state, stages[0]), "backup");
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
    { step: "prepare", task: "backup" },
  );
  assert.deepEqual(
    initialPosition(state, {
      lifecycle: { source_backup: { available: true } },
    } as TranslationState),
    { step: "context", task: "names" },
  );
});

test("the Project page continues past a finished one-way step but keeps a later saved position", () => {
  const translation = {
    lifecycle: { source_backup: { available: true } },
    git: { configured: false },
  } as TranslationState;
  const state = {
    projectId: "game",
    engine: "MVMZ",
    step: "prepare",
    task: "backup",
    preferences: { values: { selected: [] } },
    files: [],
    runs: [],
    phaseRuns: {},
    readiness: { outputs: [], applied: [] },
    comparisons: { status: "not_needed" },
    contextSetup: { documents: {}, layoutStatus: "missing" },
    speakerSetup: {},
    speakerScan: {},
    preparation: { complete: false },
    artifacts: [],
  } as unknown as GuidedState;
  assert.deepEqual(guidedProgress(state, translation).current, {
    step: "prepare",
    task: "format",
    stage: "Prepare",
    title: "Prepare game files",
    advanced: true,
  });
  // Apply counts as done once outputs are applied, with earlier work open.
  state.step = "apply";
  state.task = "apply";
  state.preferences.values.selected = ["Map001.json"];
  state.readiness.outputs = state.readiness.applied = ["Map001.json"];
  const progress = guidedProgress(state, translation);
  assert.ok(
    progress.stages.some((stage) => stage.id === "apply" && stage.done),
  );
  assert.equal(progress.current.task, "apply");
  // Optional stages finish once their work reaches the game with nothing
  // waiting: an edited image awaiting review keeps Images open.
  state.artifacts = [{ current: true }] as GuidedState["artifacts"];
  const images = {
    projectId: state.projectId,
    counts: { applied: 1, ready: 0, needsReview: 1, blocked: 0 },
  } as unknown as ImageManagerState;
  const finished = () =>
    guidedProgress(state, translation, { images })
      .stages.filter((stage) => stage.done === stage.total)
      .map((stage) => stage.id);
  assert.deepEqual(finished(), ["apply", "review"]);
  images.counts.needsReview = 0;
  assert.deepEqual(finished(), ["images", "apply", "review"]);
});
