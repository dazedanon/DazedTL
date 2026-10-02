import assert from "node:assert/strict";
import test from "node:test";
import type { GuidedState, TranslationState } from "../app/src/api/contracts.ts";
import { initialPosition, runPhase, runStage, stagesFor } from "../app/src/features/guided/workflow.ts";

test("saved runs choose their owning task instead of obsolete Prepare or native progress labels", () => {
  const translation = { lifecycle: { source_backup: { available: true } }, git: { configured: true } } as TranslationState;
  const state = { engine: "MVMZ", step: "prepare", task: null, phase: "advanced", run: { mode: "batch", phase: "batch_approval", status: "waiting" } } as GuidedState;
  assert.equal(runPhase(state), "advanced");
  assert.deepEqual(initialPosition(state, translation), { step: "advanced", task: "run" });
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
  assert.deepEqual(initialPosition(state, translation), { step: "advanced", task: "variables" });
  state.run!.logicalPhase = "dialogue"; state.phase = "advanced";
  assert.equal(runPhase(state), "dialogue");
  assert.deepEqual(stagesFor("ACE").at(-1)!.tasks.map((task) => task.id), ["package"]);
});
