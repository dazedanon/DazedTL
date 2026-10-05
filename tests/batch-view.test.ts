import assert from "node:assert/strict";
import test from "node:test";
import type { Job } from "../app/src/api/contracts.ts";
import { batchInProgress, batchProgress, batchRuns, canRetrySaving, canReapplyBatch, batchOutcome, batchMonitorRows, totalBatchProgress } from "../app/src/features/guided/batchView.ts";

test("Total Batch progress retains completed requests when another provider batch starts", () => {
  const completed = { id: "first", status: "completed", total: 74, counts: { succeeded: 74 } };
  const next = { id: "next", status: "validating", total: 68, counts: { succeeded: 0, errored: 0, canceled: 0, expired: 0 } };
  assert.deepEqual(totalBatchProgress([completed, next]), { total: 142, finished: 74 });
  assert.deepEqual(totalBatchProgress([completed, next], 52), { total: 194, finished: 74 });
  assert.deepEqual(totalBatchProgress([completed], 120), { total: 194, finished: 74 });
  assert.deepEqual(totalBatchProgress([completed, { ...completed, id: "clarification", total: 8, counts: { succeeded: 8 }, clarification: true }], 120), { total: 194, finished: 74 });
  assert.deepEqual(totalBatchProgress([completed, next], -1), { total: undefined, finished: undefined });
  assert.deepEqual(totalBatchProgress([completed, { ...next, status: "in_progress", counts: { ...next.counts, succeeded: 20, errored: 2 } }]), { total: 142, finished: 96 });
  assert.deepEqual(totalBatchProgress([completed, { ...next, status: "completed", counts: { ...next.counts, succeeded: 68 } }]), { total: 142, finished: 142 });
  // Missing or contradictory receipts must not become zero or fabricated completion.
  for (const counts of [{}, { succeeded: null }, { succeeded: 69 }]) {
    assert.deepEqual(totalBatchProgress([completed, { ...next, counts }]), { total: 142, finished: undefined });
  }
  assert.deepEqual(totalBatchProgress([completed, { ...next, total: null }]), { total: undefined, finished: undefined });
  assert.deepEqual(totalBatchProgress([]), { total: undefined, finished: undefined });
});

test("Batch monitoring keeps unknown counts unknown and interrupted work recoverable", () => {
  const batch = { id: "provider", status: "in_progress", total: 10, counts: {} };
  assert.deepEqual(batchProgress(batch), { total: 10, finished: undefined });
  const counts = { succeeded: 3, errored: 1, canceled: 0, expired: 0 };
  assert.deepEqual(batchProgress({ ...batch, counts }), { total: 10, finished: 4 });
  assert.equal(batchProgress({ ...batch, counts: { ...counts, succeeded: null } }).finished, undefined);
  assert.equal(batchProgress({ ...batch, counts: { ...counts, succeeded: 11 } }).finished, undefined);
  const paused = { id: "run", mode: "batch", status: "stopped", phase: "poll_status", process: { batches: [batch], retryBlocked: true, errors: [] } } as Job;
  const completed = { ...paused, id: "finished", status: "complete", process: { ...paused.process!, retryBlocked: false, batches: [{ ...batch, status: "completed" }] } };
  const saved = { ...completed, outputs: { "Items.json": "retained" }, outputsAvailable: true };
  assert.equal(canReapplyBatch(saved), true);
  for (const unavailable of [{ ...saved, status: "running" }, { ...saved, outputsAvailable: false },
    { ...saved, outputs: {} }, { ...saved, temporary: true }, { ...saved, mode: "estimate" }]) {
    assert.equal(canReapplyBatch(unavailable), false);
  }
  assert.deepEqual(batchRuns([completed, paused]), [paused]);
  assert.equal(batchRuns([completed, paused], true).length, 2);
  // Grouping by date must not split a day around an older active run.
  const recent = { ...completed, created: "2026-10-05T12:00:00Z" }, older = { ...paused, created: "2026-10-04T12:00:00Z" };
  assert.deepEqual(batchRuns([older, recent], true), [recent, older]);
  assert.equal(canRetrySaving(paused), false);
  const collected = { ...paused, process: { ...paused.process!, resultsCollected: true, received: 1, monitoring: { state: "save_error" as const, message: "Local processing failed" }, batches: [{ ...batch, status: "cancelled" }] } };
  assert.equal(canRetrySaving(collected), true);
  assert.equal(canRetrySaving({ ...collected, process: { ...collected.process, remaining: 445 } }), false);
  assert.equal(canRetrySaving({ ...collected, process: { ...collected.process, received: 0 } }), false);
  const failed = { ...batch, status: "completed", counts: { succeeded: 0, errored: 10 } };
  assert.equal(batchOutcome(failed, paused).label, "Failed");
  assert.equal(batchOutcome(failed, paused).pending, false);
  assert.equal(batchOutcome(failed, paused).active, false);
  assert.equal(batchOutcome({ ...batch, status: 'validating' }, paused).active, true);
  assert.equal(batchOutcome({ ...batch, status: 'unknown' }, paused).active, false);
  assert.equal(batchOutcome({ ...batch, status: 'completed' }, { ...paused, status: 'running', phase: 'consume' }).active, true);
  assert.equal(batchOutcome({ ...failed, counts: { succeeded: 8, errored: 2 } }, paused).label, "Partial");
  assert.equal(batchOutcome({ ...batch, status: "ended", counts: { succeeded: 10 } }, completed).label, batchOutcome({ ...batch, status: "completed", counts: { succeeded: 10 } }, completed).label);
  // A completion icon must not certify unknown, partial or still-saving results.
  const successful = { ...batch, status: "completed", counts: { succeeded: 10 } };
  assert.equal(batchOutcome(successful, completed).successful, true);
  for (const row of [{ ...batch, status: "completed" }, failed, { ...failed, counts: { succeeded: 8, errored: 2 } },
    { ...successful, status: "in_progress" }, { ...successful, status: "failed" }]) {
    assert.equal(batchOutcome(row, paused).successful, false);
  }
  assert.equal(batchOutcome(successful, { ...paused, status: "running", phase: "consume" }).successful, false);
  assert.equal(batchOutcome({ ...batch, status: "failed" }, paused).failed, true);
  assert.equal(canRetrySaving({ ...collected, status: "running" }), false);
  assert.equal(canRetrySaving({ ...collected, process: { ...collected.process, resultsCollected: false } }), false);
  assert.equal(canRetrySaving({ ...collected, process: { ...collected.process, monitoring: { state: "monitoring", message: "" } } }), false);
  const missing = { ...paused, process: { retryBlocked: true, errors: [] } };
  assert.equal(batchRuns([missing]).length, 0);
  assert.equal(batchRuns([missing], true).length, 1);
  const capacity = { ...missing, status: "running", phase: "poll_capacity", process: { remaining: 450, errors: [] } };
  assert.deepEqual(batchRuns([capacity]), [capacity]);
  assert.equal(batchMonitorRows(capacity)[0].active, true);
  assert.equal(batchMonitorRows(capacity)[0].failed, false);
  // Failed provider work used to remain In progress solely because its
  // recovery guard, stale worker phase or monitor state was still present.
  for (const status of ["failed", "expired", "cancelled", "canceled", "completed", "ended", "unknown"]) {
    const ended = { ...paused, status: "running", phase: "poll_status",
      process: { ...paused.process!, remaining: 15, batches: [{ ...batch, status, counts: { succeeded: 0, errored: 10 } }] } };
    assert.equal(batchInProgress(ended), false, status);
    assert.deepEqual(batchRuns([ended]), []);
    assert.deepEqual(batchRuns([ended], true), [ended]);
    assert.equal(batchOutcome(ended.process.batches[0], ended).pending, false);
  }
  for (const status of ["validating", "in_progress", "finalizing", "cancelling", "canceling"]) {
    assert.equal(batchInProgress({ ...paused, process: { ...paused.process!, batches: [{ ...batch, status }] } }), true);
  }
  assert.equal(batchInProgress({ ...paused, status: "running", process: { ...paused.process!, batches: [successful], remaining: 20 } }), true);
  assert.equal(batchInProgress(collected), false);
  assert.equal(batchInProgress({ ...collected, process: { ...collected.process, monitoring: { state: "collecting", message: "" }, batches: [successful] } }), true);
  assert.equal(batchInProgress({ ...paused, process: { ...paused.process!, batches: [failed], monitoring: { state: "collecting", message: "" } } }), false);
  assert.equal(batchOutcome(failed, { ...paused, status: "running", phase: "consume" }).active, false);
  for (const state of ["error", "blocked", "save_error"] as const) {
    assert.equal(batchInProgress({ ...paused, process: { ...paused.process!, batches: [successful], monitoring: { state, message: "" } } }), false);
  }
});

test("Compact Batch rows retain active clarification controls and cannot hide unfinished work behind completed chunks", () => {
  const completed = { id: "original", status: "completed", total: 62, counts: { succeeded: 62 } };
  const retry = { id: "retry", status: "in_progress", total: 5, counts: { succeeded: 1 }, clarification: true };
  const job = { id: "run", mode: "batch", status: "stopped", phase: "poll_status",
    process: { batches: [completed, retry], remaining: 388, errors: [] } } as Job;
  const rows = batchMonitorRows(job);
  assert.deepEqual(rows.map(row => row.batch?.id), ["retry"]);
  assert.equal(rows[0].active, true);
  assert.equal(rows[0].successful, false);
  const next = { ...completed, id: "next", status: "validating", counts: {} };
  // Concurrent providers must retain all cancellation targets, even if a later receipt is terminal.
  assert.deepEqual(batchMonitorRows({ ...job, process: { ...job.process!, batches: [completed, retry, next, completed] } }).map(row => row.batch?.id), ["retry", "next"]);
  const finished = { ...job, status: "complete", outputs: { "Map001.json": "saved" }, outputsAvailable: true,
    process: { ...job.process!, remaining: 0, batches: [completed, { ...retry, status: "completed", counts: { succeeded: 5 } }] } };
  assert.equal(batchMonitorRows(finished).length, 1);
  assert.equal(batchMonitorRows(finished)[0].successful, true);
  assert.match(batchMonitorRows(finished)[0].summary, /^62\b/); // Retries must not inflate original request totals.
  for (const process of [{ ...finished.process, remaining: 388 },
    { ...finished.process, monitoring: { state: "blocked" as const, message: "Review retained receipts" } },
    { ...finished.process, rejected: 1, validationIssues: [{ file: "Map001.json", rejected: 1 }] }]) {
    const [row] = batchMonitorRows({ ...finished, process });
    assert.equal(row.successful, false);
    assert.equal(row.failed, true);
    assert.equal(row.active, false);
  }
  assert.equal(batchMonitorRows({ ...finished, status: "running", phase: "consume" })[0].active, true);
  assert.equal(batchMonitorRows({ ...job, process: { batches: [{ ...completed, status: "unknown", counts: {} }], errors: [] } })[0].successful, false);
});
