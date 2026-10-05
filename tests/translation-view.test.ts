import assert from "node:assert/strict";
import test from "node:test";
import { historyOutcome } from "../app/src/features/guided/historyView.ts";
import type { GuidedState, Job, RunPayload } from "../app/src/api/contracts.ts";
import { completeForSelection, estimateFollowup, preparationFollowup, estimateRequestCount, filePreviewRun, fileRun, fileMetricRun, fileStatus, phaseRun, translationTaskComplete, blockingBatches, needsSubmissionReview, canResumeRun, requestContext, translatedLines, translationStopLabel, observedRun } from "../app/src/features/guided/translationView.ts";

test("a later event-code task cannot inherit completion from map outputs or an old Apply receipt", () => {
  const maps: Job = { id: "maps", logicalPhase: "dialogue", mode: "batch", status: "complete", message: "", log: [], files: ["Map001.json", "Map002.json"], outputs: { "Map001.json": "hash", "Map002.json": "missing" }, availableOutputs: ["Map001.json"], outputsAvailable: false, appliedOutputs: [] };
  assert.equal(fileStatus("Map001.json", phaseRun([maps], "advanced")).label, "Ready");
  assert.equal(fileStatus("Map001.json", phaseRun([maps], "dialogue")).label, "Saved");
  assert.equal(fileStatus("Map002.json", maps).label, "Output unavailable");
  assert.equal(fileStatus("Map001.json", { ...maps, partialOutputs: ["Map001.json"] }).label, "Progress saved");
  const rejected = { ...maps, availableOutputs: ["Map001.json"], partialOutputs: ["Map001.json"],
    process: { rejected: 2, validationIssues: [{ file: "Map001.json", rejected: 2 }], errors: [] } };
  assert.equal(fileStatus("Map001.json", rejected).tone, "warning");
  assert.equal(fileStatus("Map002.json", rejected).label, "Output unavailable");
  assert.equal(fileStatus("Map001.json", { ...rejected, retiredFiles: ["Map001.json"] }).tone, "idle");
  assert.equal(historyOutcome({ ...rejected, outputs: { "Map001.json": "hash" } }).kind, "partial");
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

// Clearing selection or finishing in separate runs must not erase task progress;
// completing only a selected subset must not certify the entire file group.
test("main-text tasks combine verified files across runs independently of selection", () => {
  const items: Job = { id: "items", logicalPhase: "database", mode: "batch", status: "complete", message: "", log: [],
    files: ["Items.json"], outputs: { "Items.json": "hash" }, availableOutputs: ["Items.json"], appliedOutputs: ["Items.json"] };
  const actors = { ...items, id: "actors", keptForHistory: true, files: ["Actors.json"], outputs: { "Actors.json": "hash" }, availableOutputs: ["Actors.json"], appliedOutputs: [] };
  const empty = { ...items, id: "empty", files: ["Armors.json"], outputs: {}, availableOutputs: [], process: { noRequestFiles: ["Armors.json"], errors: [] } };
  const state = { files: [{ name: "Items.json", group: "database" }, { name: "Actors.json", group: "database" }, { name: "Armors.json", group: "database" }, { name: "Map001.json", group: "dialogue" }],
    runs: [empty, actors, items], sourceStatus: { changed: [], ready: [] }, preferences: { values: { selected: [] } } } as unknown as GuidedState;
  for (const selected of [[], ["Items.json"], ["Items.json", "Actors.json", "Armors.json"], ["Map001.json"]]) {
    state.preferences.values.selected = selected;
    assert.equal(translationTaskComplete(state, "database"), true);
    assert.equal(translationTaskComplete(state, "dialogue"), false);
  }
  assert.equal(translationTaskComplete({ ...state, runs: [empty, items] }, "database"), false);
  assert.equal(translationTaskComplete({ ...state, files: [] }, "database"), false);
  assert.equal(translationTaskComplete({ ...state, runs: [{ ...items, mode: "estimate" }, ...state.runs] }, "database"), true);
  assert.equal(translationTaskComplete({ ...state, runs: [actors, items, { ...empty, process: { errors: [] } }] }, "database"), false);
  assert.equal(translationTaskComplete({ ...state, runs: [actors, items, { ...empty, outputs: { "Armors.json": "missing" } }] }, "database"), false);
  const maps = { ...items, id: "maps", logicalPhase: "dialogue" as const, files: ["Map001.json"], outputs: { "Map001.json": "hash" }, availableOutputs: ["Map001.json"] };
  assert.equal(translationTaskComplete({ ...state, runs: [maps, ...state.runs] }, "dialogue"), true);
  assert.equal(translationTaskComplete({ ...state, runs: [maps, ...state.runs].map(run => ({ ...run, logicalPhase: "advanced" })) }, "dialogue"), false);
});

// Historical success cannot hide unfinished replacement work, unavailable output,
// or a source reload, including when the active worker is an older attempt.
test("main-text completion respects current file ownership and output validity", () => {
  const saved: Job = { id: "saved", logicalPhase: "database", mode: "translate", status: "complete", message: "", log: [],
    files: ["Items.json"], outputs: { "Items.json": "hash" }, availableOutputs: ["Items.json"], appliedOutputs: ["Items.json"] };
  const state = { files: [{ name: "Items.json", group: "database" }], runs: [saved], sourceStatus: { changed: [], ready: [] } } as Pick<GuidedState, "files" | "runs" | "sourceStatus">;
  for (const patch of [
    { status: "running" }, { status: "waiting" }, { temporary: true },
    { partialOutputs: ["Items.json"] }, { availableOutputs: [] },
    { status: "failed", outputs: {}, availableOutputs: [], keptForHistory: true },
    { mode: "batch", status: "interrupted", phase: "poll_status" },
  ]) {
    assert.equal(translationTaskComplete({ ...state, runs: [{ ...saved, ...patch, id: "new" }, saved] }, "database"), false, JSON.stringify(patch));
  }
  assert.equal(translationTaskComplete({ ...state, runs: [saved, { ...saved, id: "resumed", status: "running" }] }, "database"), false);
  assert.equal(translationTaskComplete({ ...state, sourceStatus: { ...state.sourceStatus, changed: ["Items.json"] } }, "database"), false);
  assert.equal(translationTaskComplete({ ...state, sourceStatus: { ...state.sourceStatus, retired: [saved.id] } }, "database"), false);
  assert.equal(translationTaskComplete({ ...state, runs: [{ ...saved, retiredFiles: ["Items.json"] }] }, "database"), false);
});

test("request comparisons reject misaligned or unvalidated Live responses and mismatched Batch keys", () => {
  const payload = { source: { Line1: "薬", Line2: "毒" }, state: "validated", response: ["Medicine", "Poison"] } as RunPayload;
  assert.deepEqual(translatedLines(payload), { Line1: "Medicine", Line2: "Poison" });
  assert.equal(translatedLines({ ...payload, response: ["Wrong request"] }), null);
  assert.equal(translatedLines({ ...payload, state: "received" }), null);
  assert.deepEqual(translatedLines({ ...payload, state: "received", response: { text: '{"Line2":"Poison","Line1":"Medicine"}' } }), { Line2: "Poison", Line1: "Medicine" });
  assert.equal(translatedLines({ ...payload, response: { text: '{"Line1":"Medicine","Line3":"Poison"}' } }), null);
  assert.equal(translatedLines({ ...payload, response: { text: "Unstructured reply" } }), null);
  assert.equal(translatedLines({ ...payload, state: "rejected", response: { text: '{"Line1":"Medicine","Line2":"Poison"}' } }), null);
  assert.equal(translatedLines({ ...payload, state: "unused", response: { text: '{"Line1":"Medicine","Line2":"Poison"}' } }), null);
  const raw = { text: '{"translations":["__PROTECTED_0__Medicine","Poison"]}', refusal: null };
  assert.deepEqual(translatedLines({ ...payload, response: raw, translations: ["\\C[1]Medicine", "Poison"] }), { Line1: "\\C[1]Medicine", Line2: "Poison" });
  assert.equal(translatedLines({ ...payload, state: "received", response: raw, translations: null }), null);
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
  assert.equal(canResumeRun(unresolved), false);
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
  // A delayed speaker approval must not reopen after it was answered. A
  // distinct Batch approval retains the verified name result for its review.
  const names = { ...job, id: "paid", mode: "batch", status: "waiting", approval: { token: "names", kind: "speakers", detail: {} } } as Job;
  assert.deepEqual(preparationFollowup(names.id, [names], "names"), { kind: "waiting" });
  const translated = { ...names, approval: { token: "maps", kind: "batch", detail: {} },
    nameTranslation: { state: "saved", count: 1, rows: [{ source: "回想部屋", translation: "Recollection Room" }] } } as Job;
  assert.equal(preparationFollowup(names.id, [translated], "names").kind, "review");
  assert.equal(preparationFollowup(names.id, [translated], "names").job?.nameTranslation, translated.nameTranslation);
  assert.equal(preparationFollowup(names.id, [{ ...translated, approval: undefined, status: "failed" }], "names").kind, "failed");
});

// Hiding preparation controls must not remove the exit from paid execution or
// confuse stopping local monitoring with canceling a submitted provider Batch.
test("translation stop controls distinguish preparation, approval and running work", () => {
  const job = { id: "run", mode: "batch", status: "running", log: [], message: "" } as Job;
  assert.equal(translationStopLabel(undefined), null);
  const temporary = { ...job, temporary: true, status: "stopped", files: ["Items.json"] };
  assert.equal(canResumeRun(temporary), false);
  assert.equal(fileStatus("Items.json", temporary).label, "Ready");
  assert.equal(fileStatus("Items.json", { ...temporary, status: "failed" }).label, "Needs attention");
  assert.equal(translationStopLabel({ ...job, mode: "estimate" }), null);
  for (const phase of [undefined, "preparing", "collect", "collect_done", "submit"]) {
    assert.equal(translationStopLabel({ ...job, phase, process: { submitted: 0, errors: [] } }), null);
  }
  assert.equal(translationStopLabel({ ...job, process: { submitted: 1, errors: [] } }), null);
  assert.equal(translationStopLabel({ ...job, phase: "poll_status" }), null);
  assert.equal(translationStopLabel({ ...job, phase: "consume", process: { submitted: 1, errors: [] } }), null);
  assert.equal(translationStopLabel({ ...job, mode: "translate" }), "Stop translation");
  for (const mode of ["batch", "translate"]) {
    assert.equal(translationStopLabel({ ...job, mode, status: "waiting", approval: { token: "review", kind: "batch", detail: {} } }), null);
    for (const status of ["complete", "failed", "stopped", "interrupted", "canceled"]) {
      assert.equal(translationStopLabel({ ...job, mode, status, phase: "poll" }), null);
    }
  }
});

// An earlier checkpoint must not freeze the rows at Saved while a provider is
// working. A resumed older run also needs to displace a newer finished attempt.
test("file metrics survive unchanged passes and advance only with changed output", () => {
  const old = { id: "old", logicalPhase: "database", mode: "batch", status: "complete", files: ["Items.json"], changedOutputs: ["Items.json"],
    process: { errors: [], fileMetrics: { "Items.json": { cost: .125, seconds: 12.5 } } } } as Job;
  const skipped = { ...old, id: "skipped", status: "running", changedOutputs: [], process: { errors: [], noRequestFiles: ["Items.json"], fileMetrics: {} } };
  assert.equal(fileMetricRun([skipped, old], "database", "Items.json"), old);
  const unchanged = { ...skipped, status: "complete", process: { errors: [], fileMetrics: { "Items.json": { cost: 0, seconds: .1 } } } };
  assert.equal(fileMetricRun([unchanged, old], "database", "Items.json"), old);
  const changed = { ...unchanged, changedOutputs: ["Items.json"] };
  assert.equal(fileMetricRun([changed, old], "database", "Items.json"), changed);
  const unrecorded = { ...changed, process: { errors: [] } };
  assert.equal(fileMetricRun([unrecorded, old], "database", "Items.json"), unrecorded);
  assert.equal(fileMetricRun([old], "database", "Items.json", [old.id]), undefined);
  assert.equal(fileMetricRun([{ ...old, retiredFiles: ["Items.json"] }], "database", "Items.json"), undefined);
  assert.equal(fileMetricRun([old], "dialogue", "Items.json"), undefined);
  const resumed = { ...old, status: "running" };
  assert.equal(fileMetricRun([changed, resumed], "database", "Items.json"), resumed);
  assert.equal(fileMetricRun([{ ...skipped, changedOutputs: undefined }, old], "database", "Items.json"), old);
  assert.equal(fileMetricRun([{ ...changed, mode: "estimate" }, { ...changed, temporary: true }, old], "database", "Items.json"), old);
});

test("file status follows active and automatically monitored Batch work before retained outputs", () => {
  const checkpoint = { id: "batch", logicalPhase: "database", mode: "batch", status: "running", phase: "poll_status", files: ["Items.json"],
    outputs: { "Items.json": "saved" }, availableOutputs: ["Items.json"], partialOutputs: ["Items.json"],
    process: { retryBlocked: true, requests: [{ index: 0, file: "Items.json", state: "submitted", sourceItems: 1 }], errors: [] }, log: [], message: "" } as Job;
  assert.equal(fileStatus("Items.json", checkpoint).label, "In Batch");
  const withSkipped = { ...checkpoint, files: ["Items.json", "Armors.json"], process: { ...checkpoint.process!, noRequestFiles: ["Armors.json"] } };
  assert.equal(fileStatus("Armors.json", withSkipped).label, "No new requests");
  assert.equal(fileStatus("Armors.json", { ...withSkipped, temporary: true, status: "waiting" }).label, "No new requests");
  assert.equal(fileStatus("Armors.json", { ...withSkipped, status: "complete", availableOutputs: ["Armors.json"] }).label, "Saved");
  assert.notEqual(fileStatus("Armors.json", { ...withSkipped, mode: "translate" }).label, "No new requests");
  const received = { ...checkpoint, process: { ...checkpoint.process!, requests: [{ index: 0, file: "Items.json", state: "received", sourceItems: 1 }] } };
  assert.equal(fileStatus("Items.json", received).label, "Received");
  assert.equal(fileStatus("Items.json", { ...received, phase: "consume" }).label, "Saving results");
  assert.equal(fileStatus("Items.json", { ...received, phase: "consume", partialOutputs: [] }).label, "Saved");
  assert.equal(fileStatus("Items.json", { ...checkpoint, status: "stopped" }).label, "In Batch");
  assert.equal(fileStatus("Items.json", { ...checkpoint, status: "complete", partialOutputs: [] }).label, "Saved");
  assert.equal(fileStatus("Items.json", { ...checkpoint, mode: "translate" }).label, "Translating");
  assert.equal(fileStatus("Items.json", { ...checkpoint, process: { errors: [] } }).label, "In Batch");
  const completed = { ...checkpoint, id: "newer", status: "complete", partialOutputs: [] };
  assert.equal(fileRun([completed, checkpoint], "database", "Items.json"), checkpoint);
  assert.equal(fileRun([completed, checkpoint], "dialogue", "Items.json"), undefined);
  assert.equal(fileRun([completed, checkpoint], "database", "Items.json", [checkpoint.id]), completed);
  const stopped = { ...checkpoint, status: "stopped" };
  assert.deepEqual(blockingBatches([{ ...completed, mode: "estimate" }, stopped], ["Items.json"]), [stopped]);
  assert.deepEqual(blockingBatches([stopped], ["Actors.json"]), []);
  const providerFinished = { ...stopped, process: { errors: [], retryBlocked: false, resultsCollected: true, batches: [{ id: "paid", status: "completed", counts: {} }] } };
  assert.equal(canResumeRun(providerFinished), false);
  assert.equal(canResumeRun({ ...providerFinished, status: "failed", process: { ...providerFinished.process, resultsCollected: false, failed: 12 } }), false);
  assert.deepEqual(blockingBatches([providerFinished], ["Items.json"]), [providerFinished]);
  assert.deepEqual(blockingBatches([{ ...providerFinished, phase: "consume", status: "failed" }], ["Items.json"]), []);
  assert.deepEqual(blockingBatches([checkpoint], ["Actors.json"]), []);
  assert.deepEqual(blockingBatches([{ ...checkpoint, retiredFiles: ["Items.json"] }], ["Items.json"]), []);
  const monitoring = { ...stopped, process: { ...stopped.process!, monitoring: { state: "collecting" as const, message: "" } } };
  assert.equal(fileStatus("Items.json", monitoring).label, "Receiving results");
  assert.equal(canResumeRun(monitoring), false);
  assert.equal(fileStatus("Items.json", { ...monitoring, process: { ...monitoring.process, monitoring: { state: "error", message: "Retrying" } } }).label, "Needs attention");
});

// Live inspection must follow new receipts while a stale full-detail read and
// old log are retained; another project/run must never replace the selection.
test("Live inspection and file progress follow current receipts without Batch controls", () => {
  const live = { id: "live", mode: "translate", status: "running", files: ["Items.json"], updated: "2026-10-04T10:00:00Z", log: ["retained"],
    progress: { file: "Items.json", current: 0, total: 1 }, itemProgress: { file: "Items.json", current: 12, total: 50 },
    process: { requests: [{ index: 0, file: "Items.json", state: "submitted", sourceItems: 50 }], errors: [] } } as Job;
  assert.equal(fileStatus("Items.json", live).label, "Translating");
  assert.equal(fileStatus("Items.json", { ...live, process: { ...live.process!, requests: [{ index: 0, file: "Items.json", state: "validated", sourceItems: 50 }] } }).label, "Translating · 1 received");
  const rejected = { index: 1, file: "Items.json", state: "rejected", sourceItems: 50 };
  assert.equal(fileStatus("Items.json", { ...live, process: { ...live.process!, requests: [...live.process!.requests!, rejected] } }).label, "Translating · 1 received");
  assert.equal(translationStopLabel(live), "Stop translation");
  assert.equal(fileStatus("Items.json", { ...live, status: "stopped", availableOutputs: ["Items.json"], partialOutputs: ["Items.json"] }).label, "Stopped");
  assert.equal(fileStatus("Items.json", { ...live, status: "failed" }).label, "Needs attention");
  assert.equal(fileStatus("Items.json", { ...live, status: "complete", availableOutputs: ["Items.json"] }).label, "Saved");
  const completed = { ...live, updated: "2026-10-04T10:00:01Z", status: "complete", log: [] };
  assert.equal(observedRun(live, completed)?.status, "complete");
  assert.deepEqual(observedRun(live, completed)?.log, ["retained"]);
  assert.equal(observedRun(completed, live), completed);
  assert.equal(observedRun(live, { ...completed, id: "foreign" }), live);
});
