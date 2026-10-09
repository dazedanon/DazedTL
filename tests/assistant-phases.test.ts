import assert from "node:assert/strict";
import test from "node:test";
import type { TranslationProgress } from "../app/src/api/contracts.ts";
import { phaseStates } from "../app/src/features/translation/assistantPhases.ts";

test("only the assistant's reported phase reads as current, and one it left open says what remains", () => {
  const report = (
    phase: string | null,
    phases: Record<string, string>,
    images: number | null = null,
  ) =>
    ({
      updated_at: "2026-10-09T16:27:04+00:00",
      phase,
      phases,
      metrics: {
        text: { total: 3, translated: 3, reviewed: 0 },
        images: { total: images, translated: 0, reviewed: 0 },
      },
    }) as TranslationProgress;
  const marks = (steps: ReturnType<typeof phaseStates>) =>
    steps.map((step) => step.state + (step.detail ? ":" + step.detail : ""));
  // The helper keeps translation open while images remain, so a run that
  // moves on to packaging reports two active phases.
  const packaging = report("patch", {
    preparation: "complete",
    extraction: "complete",
    translation: "active",
    injection: "complete",
    qa: "complete",
    patch: "active",
  });
  assert.deepEqual(marks(phaseStates(packaging, true, true)), [
    "done",
    "done",
    "started:Images left",
    "done",
    "done",
    "current",
  ]);
  assert.equal(
    phaseStates(packaging, true, false)[2].detail,
    "Unfinished",
    "without images in scope, nothing says images remain",
  );
  // A report that names no phase leaves its furthest active one current.
  assert.deepEqual(
    marks(
      phaseStates(
        report(null, { preparation: "active", extraction: "active" }, 0),
        true,
        true,
      ),
    ),
    ["started:Unfinished", "current", "next", "next", "next", "next"],
  );
  assert.deepEqual(
    marks(phaseStates(null, true, true)),
    ["current", "next", "next", "next", "next", "next"],
    "the first helper call starts preparation before any report",
  );
});
