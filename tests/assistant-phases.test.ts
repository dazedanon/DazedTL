import assert from "node:assert/strict";
import test from "node:test";
import { phaseStates } from "../app/src/features/translation/assistantPhases.ts";

test("only the assistant's reported phase reads as current, and Images shows only in scope", () => {
  const report = (phase: string | null, phases: Record<string, string>) =>
    ({ updated_at: "2026-10-09T16:27:04+00:00", phase, phases }) as never;
  const marks = (steps: ReturnType<typeof phaseStates>) =>
    steps.map((step) => `${step.label}:${step.state}`);
  // Images during an API run leave translation active behind the current
  // phase, so two phases are active at once.
  const imagesDuringRun = report("images", {
    preparation: "complete",
    extraction: "complete",
    translation: "active",
    images: "active",
  });
  assert.deepEqual(marks(phaseStates(imagesDuringRun, true, true)), [
    "Preparation:done",
    "Extraction:done",
    "Translation:started",
    "Images:current",
    "Injection:next",
    "QA:next",
    "Patch:next",
  ]);
  // A report that names no phase leaves its furthest active one current.
  const unnamed = report(null, { preparation: "active", extraction: "active" });
  assert.deepEqual(marks(phaseStates(unnamed, true, false)), [
    "Preparation:started",
    "Extraction:current",
    "Translation:next",
    "Injection:next",
    "QA:next",
    "Patch:next",
  ]);
  assert.deepEqual(
    phaseStates(null, true, false).map((step) => step.state),
    ["current", "next", "next", "next", "next", "next"],
    "the first helper call starts preparation before any report",
  );
});
