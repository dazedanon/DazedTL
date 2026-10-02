import assert from "node:assert/strict";
import test from "node:test";
import type { GuidedState, TranslationState } from "../app/src/api/contracts.ts";
import { initialPosition, runPhase, runStage, stagesFor, unfinishedRun } from "../app/src/features/guided/workflow.ts";

test("saved runs choose their owning task instead of obsolete Prepare or native progress labels", () => {
  const translation = { lifecycle: { source_backup: { available: true } }, git: { configured: true } } as TranslationState;
  const state = { engine: "MVMZ", step: "prepare", task: null, phase: "advanced", run: { mode: "batch", phase: "batch_approval", status: "waiting" } } as GuidedState;
  assert.equal(runPhase(state), "advanced");
  assert.deepEqual(initialPosition(state, translation), { step: "translate", task: "run" });
  state.run!.mode = "speakers";
  assert.deepEqual(initialPosition(state, translation), { step: "context", task: "run" });
  state.step = "context"; state.task = "glossary";
  assert.deepEqual(initialPosition(state, translation), { step: "context", task: "guidance" });
  state.run!.mode = "translate"; state.run!.phase = "complete"; state.phase = "database";
  assert.equal(runPhase(state), "database");
  assert.equal(runStage(state), "translate");
  state.step = "translate"; state.task = "dialogue";
  assert.deepEqual(initialPosition(state, translation), { step: "translate", task: "main-text" });
  state.task = "variables";
  assert.deepEqual(initialPosition(state, translation), { step: "translate", task: "other-event-text" });
  state.run!.logicalPhase = "dialogue"; state.phase = "advanced";
  assert.equal(runPhase(state), "dialogue");
  state.task = "main-text";
  assert.deepEqual(initialPosition(state, translation), { step: "translate", task: "main-text" });
  for (const task of ["audit", "sources", "advanced-run", "variables"]) {
    state.step = "advanced"; state.task = task;
    assert.deepEqual(initialPosition(state, translation), { step: "translate", task: "other-event-text" });
  }
  assert.deepEqual(stagesFor("MVMZ").find((stage) => stage.id === "translate")!.tasks.map((task) => task.id), ["main-text", "other-event-text"]);
  assert.deepEqual(stagesFor("ACE").at(-1)!.tasks.map((task) => task.id), ["package"]);
  state.step = "apply"; state.task = "plugins";
  assert.deepEqual(initialPosition(state, translation), { step: "plugins", task: "plugins" });
  state.task = "image-manager";
  assert.deepEqual(initialPosition(state, translation), { step: "images", task: "images" });
  state.step = "images"; state.task = "images";
  assert.deepEqual(initialPosition(state, translation), { step: "images", task: "images" });
  assert.equal(stagesFor("MVMZ").findIndex((stage) => stage.id === "images"), stagesFor("MVMZ").findIndex((stage) => stage.id === "plugins") + 1);
  for (const status of ["failed", "stopped", "interrupted", "running", "waiting"]) {
    state.run!.status = status;
    assert.equal(unfinishedRun(state), true);
  }
  for (const status of ["complete", "canceled"]) {
    state.run!.status = status;
    assert.equal(unfinishedRun(state), false);
  }
});
