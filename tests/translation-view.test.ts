import assert from "node:assert/strict";
import test from "node:test";
import { historyOutcome } from "../app/src/features/guided/historyView.ts";
import type { Job, RunPayload } from "../app/src/api/contracts.ts";
import { completeForSelection, estimateFollowup, estimateRequestCount, filePreviewRun, fileStatus, phaseRun, needsSubmissionReview, canResumeRun, requestContext, translatedLines, translationStopLabel } from "../app/src/features/guided/translationView.ts";

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
  // Dismissal must not revive the previous attempt.
  assert.equal(phaseRun([{ ...maps, id: "kept", keptForHistory: true }, partial], "dialogue"), undefined);
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
  // A current estimate must take precedence over an older completed output.
  assert.equal(filePreviewRun("Items.json", current, estimate, previous), estimate);
  assert.equal(filePreviewRun("Items.json", { ...current, status: "running" }, estimate, previous)?.mode, current.mode);
  assert.equal(filePreviewRun("Items.json", current, estimate, previous, false), current);
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

});

// Prevent dumping the static prompt into the context preview or substituting
// current glossary entries for the specific request's retained matches.
test("context preview separates matched guidance from static prompts and translatable source", () => {
  const dynamic = "Here are glossary entries with the approved spelling and translation.\n# Speakers\nアスター (Aster)";
  const staticPrompt = "Rules with an example\n```json\n{}\n```\nDo not remove control codes.";
  const source = { Line1: "薬" };
  const messages = [{ role: "system", content: "```\n" + staticPrompt + "\n```\n\n" + dynamic },
    { role: "user", content: "Preceding Japanese Source Context (untranslated):\nUse for scene context.\n```\n前の台詞\n```" },
    { role: "user", content: "Request Instructions:\n```\nTranslate item names.\n```" },
    { role: "user", content: '```json\n{"Line1":"薬"}\n```' }];
  const payload = { source, messages } as unknown as RunPayload;
  const sections = requestContext(payload);
  assert.deepEqual(sections.map(section => section.text), [dynamic, "前の台詞", "Translate item names."]);
  assert.equal(sections[2].notes, true);
  assert.deepEqual(requestContext({ ...payload, messages: messages.slice(1), system: [{type:"text",text:staticPrompt},{type:"text",text:dynamic}] }), sections);
  assert.deepEqual(requestContext({ ...payload, messages: [{role:"system",content:staticPrompt}], context: null }), []);
  assert.deepEqual(requestContext({ ...payload, context: {source_items:["Exact saved scene"],instructions:["Exact saved instructions"]} }).map(section => section.text), [dynamic,"Exact saved scene","Exact saved instructions"]);
});

// Protect stale overlapping failures becoming current after an estimate, a
// selection change or dismissal, while unresolved receipts remain actionable.
test("new attempts supersede historical warnings without releasing submission protections", () => {
  const old = { id: "old", created: "2020-01-01", updated: "2030-01-01", mode: "batch", logicalPhase: "database", files: ["Items.json", "Actors.json"], status: "failed", phase: "poll", process: { failed: 82, retryBlocked: false, requests: [{ index: 0, file: "Items.json", state: "failed", sourceItems: 1 }] } } as Job;
  const next = { ...old, id: "next", created: "2026-01-01", files: ["Actors.json"] };
  assert.equal(phaseRun([old, next], "database", ["Items.json"]), undefined);
  assert.equal(phaseRun([old, next], "database", ["Actors.json"]), next);
  assert.equal(phaseRun([{ ...next, mode: "estimate" }, old], "database"), undefined);
  assert.equal(phaseRun([{ ...next, keptForHistory: true }, old], "database"), undefined);
  assert.equal(fileStatus("Items.json", old, true).label, "Ready");
  assert.equal(needsSubmissionReview(old), false);
  assert.equal(canResumeRun(old), false);
  assert.equal(canResumeRun({ ...old, mode: "estimate", phase: "prepare" }), false);
  const unresolved = { ...old, keptForHistory: true, process: { ...old.process!, retryBlocked: true } };
  assert.equal(needsSubmissionReview(unresolved), true);
  assert.equal(canResumeRun(unresolved), true);
  const resumed = { ...unresolved, status: "running" };
  assert.equal(phaseRun([next, resumed], "database"), resumed);
});

// History must not turn local estimates, absent receipts or a stopped/failed
// worker with partial output into a successful translated-file claim.
test("history outcomes distinguish verified output from completed attempts and unresolved submissions", () => {
  const done = { id: "history", status: "complete", mode: "batch", files: ["Items.json"], process: { prepared: 0, received: 0, errors: [] } } as Job;
  assert.equal(historyOutcome(done).kind, "empty");
  assert.equal(historyOutcome({ ...done, mode: "estimate" }).kind, "estimate");
  const recorded = { ...done, outputs: { "Items.json": "hash" } };
  assert.equal(historyOutcome(recorded).kind, "finished");
  assert.equal(historyOutcome({ ...recorded, availableOutputs: [] }).kind, "missing");
  const verified = { ...recorded, availableOutputs: ["Items.json"] };
  assert.equal(historyOutcome(verified).kind, "saved");
  assert.equal(historyOutcome({ ...verified, partialOutputs: ["Items.json"] }).kind, "partial");
  assert.equal(historyOutcome({ ...verified, status: "failed" }).kind, "failed");
  assert.equal(historyOutcome({ ...verified, status: "stopped", keptForHistory: true, process: { ...done.process!, retryBlocked: true } }).kind, "review");
  assert.equal(historyOutcome({ ...verified, status: "waiting", approval: { token: "fixture", kind: "batch", detail: {} } }).kind, "approval");
});

// An old run can lack request evidence while its estimate still requires paid
// work. Conversely, a finished zero-request estimate must have an explicit result.
test("translation followup uses the matching estimate count and exits for terminal failures", () => {
  const job = { id: "new-estimate", mode: "estimate", status: "complete", estimate: { requests: 3 },
    process: { prepared: 0, errors: [] } } as Job;
  const quote = { job, current: true };
  assert.equal(estimateFollowup(job.id, quote, [job], false).kind, "review");
  assert.equal(estimateRequestCount({ ...job, estimate: { request_count: 2 } }), 2);
  assert.equal(estimateFollowup(job.id, { ...quote, job: { ...job, estimate: { requests: 0 } } }, [job], false).kind, "empty");
  assert.equal(estimateFollowup(job.id, { ...quote, job: { ...job, estimate: {} } }, [job], false).kind, "review");
  assert.equal(estimateFollowup(job.id, { ...quote, job: { ...job, status: "running" } }, [job], false).kind, "waiting");
  assert.equal(estimateFollowup(job.id, { ...quote, current: false }, [job], false).kind, "stale");
  assert.equal(estimateFollowup(job.id, quote, [job], true).kind, "stale");
  assert.equal(estimateFollowup(job.id, { job: { ...job, id: "other" }, current: true }, [job], false).kind, "stale");
  // A failed/stopped run remains visible even if quote calculation can no
  // longer produce a current entry. It must not leave Translate spinning.
  for (const status of ["failed", "stopped", "interrupted", "canceled"]) {
    assert.equal(estimateFollowup(job.id, undefined, [{ ...job, status }], false).kind, "failed");
  }
  assert.equal(estimateFollowup(job.id, undefined, [], false).kind, "waiting");
});

// Hiding preparation controls must not remove the exit from paid execution or
// confuse stopping local monitoring with canceling a submitted provider Batch.
test("translation stop controls distinguish preparation, approval and running work", () => {
  const job = { id: "run", mode: "batch", status: "running", log: [], message: "" } as Job;
  assert.equal(translationStopLabel(undefined), null);
  assert.equal(translationStopLabel({ ...job, mode: "estimate" }), null);
  for (const phase of [undefined, "preparing", "collect", "collect_done", "submit"]) {
    assert.equal(translationStopLabel({ ...job, phase, process: { submitted: 0, errors: [] } }), null);
  }
  assert.equal(translationStopLabel({ ...job, process: { submitted: 1, errors: [] } }), "Pause monitoring");
  assert.equal(translationStopLabel({ ...job, phase: "poll_status" }), "Pause monitoring");
  assert.equal(translationStopLabel({ ...job, phase: "consume", process: { submitted: 1, errors: [] } }), "Stop translation");
  assert.equal(translationStopLabel({ ...job, mode: "translate" }), "Stop translation");
  for (const mode of ["batch", "translate"]) {
    assert.equal(translationStopLabel({ ...job, mode, status: "waiting", approval: { token: "review", kind: "batch", detail: {} } }), null);
    for (const status of ["complete", "failed", "stopped", "interrupted", "canceled"]) {
      assert.equal(translationStopLabel({ ...job, mode, status, phase: "poll" }), null);
    }
  }
});
