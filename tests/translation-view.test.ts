import assert from "node:assert/strict";
import test from "node:test";
import type { Job, RunPayload } from "../app/src/api/contracts.ts";
import { completeForSelection, filePreviewRun, fileStatus, phaseRun, requestContext, translatedLines } from "../app/src/features/guided/translationView.ts";

test("a later event-code task cannot inherit completion from map outputs or an old Apply receipt", () => {
  const maps: Job = { id: "maps", logicalPhase: "dialogue", mode: "batch", status: "complete", message: "", log: [], files: ["Map001.json", "Map002.json"], outputs: { "Map001.json": "hash", "Map002.json": "missing" }, availableOutputs: ["Map001.json"], outputsAvailable: false, appliedOutputs: [] };
  assert.equal(fileStatus("Map001.json", phaseRun([maps], "advanced")).label, "Ready");
  assert.equal(fileStatus("Map001.json", phaseRun([maps], "dialogue")).label, "Saved");
  assert.equal(fileStatus("Map002.json", maps).label, "Output unavailable");
  assert.equal(fileStatus("Map001.json", { ...maps, partialOutputs: ["Map001.json"] }).label, "Progress saved");
  assert.equal(fileStatus("Map001.json", { ...maps, retiredFiles: ["Map001.json"] }).label, "Ready");
  assert.equal(fileStatus("Map001.json", { ...maps, appliedOutputs: ["Map001.json"] }).label, "Applied");
  const partial = { ...maps, status: "interrupted", availableOutputs: [], outputs: {}, process: { requests: [{ index: 0, file: "Map001.json", state: "uncertain", sourceItems: 1 }], errors: [] } };
  assert.equal(fileStatus("Map001.json", partial).label, "Check submission");
  assert.equal(phaseRun([{ ...maps, id: "kept", keptForHistory: true }, partial], "dialogue"), partial);
  // A new draft selection must not offer Apply for a different completed scope
  // while the backend snapshot still describes the previous saved selection.
  assert.equal(phaseRun([maps], "dialogue", ["Map003.json"]), undefined);
  assert.equal(phaseRun([maps], "dialogue", []), undefined);
  assert.equal(phaseRun([maps], "dialogue", ["Map001.json"]), maps);
  const complete = { ...maps, scopeComplete: true };
  assert.equal(completeForSelection(complete, ["Map002.json", "Map001.json"]), true);
  assert.equal(completeForSelection(complete, ["Map001.json"]), false);
  assert.equal(completeForSelection(complete, ["Map003.json", "Map004.json"]), false);
  assert.equal(completeForSelection(complete, []), false);
});

test("opening a file outside the current selection uses that file's retained requests", () => {
  const previous = { id: "actors", files: ["Actors.json"], status: "complete", scopeComplete: true } as Job;
  const current = { id: "items", files: ["Items.json"], status: "complete", scopeComplete: true } as Job;
  const estimate = { ...current, id: "estimate", mode: "estimate" };
  assert.equal(filePreviewRun("Actors.json", current, estimate, previous), previous);
  assert.equal(filePreviewRun("Items.json", current, estimate, previous), current);
  assert.equal(filePreviewRun("Items.json", { ...current, scopeComplete: false, status: "failed" }, estimate, previous), estimate);
  assert.equal(filePreviewRun("Unknown.json", current, estimate, previous), undefined);
  assert.equal(filePreviewRun("Items.json", previous, estimate, current, false), current);
  assert.equal(filePreviewRun("Items.json", previous, estimate, undefined, false), estimate);
});

test("request comparisons reject misaligned or unvalidated Live responses and mismatched Batch keys", () => {
  const payload = { source: { Line1: "薬", Line2: "毒" }, state: "validated", response: ["Medicine", "Poison"] } as RunPayload;
  assert.deepEqual(translatedLines(payload), { Line1: "Medicine", Line2: "Poison" });
  assert.equal(translatedLines({ ...payload, response: ["Wrong request"] }), null);
  assert.equal(translatedLines({ ...payload, state: "received" }), null);
  assert.deepEqual(translatedLines({ ...payload, state: "received", response: { text: '{"Line2":"Poison","Line1":"Medicine"}' } }), { Line2: "Poison", Line1: "Medicine" });
  assert.equal(translatedLines({ ...payload, response: { text: '{"Line1":"Medicine","Line3":"Poison"}' } }), null);
  assert.equal(translatedLines({ ...payload, response: { text: "Unstructured reply" } }), null);
  // Context embedded beside source in the final message must not disappear from the preview.
  assert.match(requestContext({ ...payload, messages: [{ role: "user", content: "Final source with contextual instruction" }] }), /contextual instruction/);
});
