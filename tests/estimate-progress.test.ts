import assert from "node:assert/strict";
import test from "node:test";
import type { Job } from "../app/src/api/contracts.ts";
import { estimateActivity } from "../app/src/features/guided/estimateActivity.ts";
import type { TranslationFlowState } from "../app/src/features/guided/useTranslationFlow.ts";
import { remainingSeconds } from "../app/src/ui/workTime.ts";

test("remaining time waits for a fair pace and grows while a long file holds it", () => {
  // Files differ widely in how long they take, so a few early ones give no
  // figure: not within five seconds, nor before a twentieth of the files
  // unless the pace has been measured for a quarter minute.
  assert.equal(
    remainingSeconds(
      [
        { at: 0, current: 1 },
        { at: 4_000, current: 300 },
      ],
      1000,
      4_000,
    ),
    undefined,
  );
  assert.equal(
    remainingSeconds(
      [
        { at: 0, current: 1 },
        { at: 10_000, current: 20 },
      ],
      1000,
      10_000,
    ),
    undefined,
  );
  const steady = [
    { at: 0, current: 100 },
    { at: 10_000, current: 200 },
  ];
  assert.equal(remainingSeconds(steady, 1000, 10_000), 80);
  // Within a file's usual time the figure runs down; past it, the wait slows
  // the pace, so a long file never reads as nearly done.
  assert.equal(remainingSeconds(steady, 1000, 10_050), 79.95);
  assert.equal(remainingSeconds(steady, 1000, 40_000), 320);
  // The pace follows the last half minute rather than a slow start.
  assert.equal(
    remainingSeconds(
      [
        { at: 0, current: 10 },
        { at: 30_000, current: 40 },
        { at: 60_000, current: 240 },
      ],
      1000,
      60_000,
    ),
    114,
  );
});

test("a Batch estimate's file counts belong to the step that reported them", () => {
  const flow = (job: Job, namesApproved = false): TranslationFlowState => ({
    phase: "dialogue",
    mode: "batch",
    files: ["Map001.json"],
    started: 0,
    stage: "batch",
    runId: "run",
    job,
    namesApproved,
  });
  const run = (phase: string, current?: number): Job => ({
    id: "run",
    status: "running",
    message: "",
    log: [],
    phase,
    progress:
      current === undefined ? null : { current, total: 10, file: "Map.json" },
    nameTranslation: { state: "saved", count: 1, rows: [] },
  });
  // A speaker scan the Batch had to repeat counts its files before the
  // requests are collected; its pace and bar are not the requests'.
  let activity = estimateActivity(flow(run("preparing", 4)));
  assert.deepEqual(
    activity.steps.map((step) => step.id),
    ["check", "estimate", "requests"],
  );
  assert.equal(activity.current, "requests");
  assert.equal(activity.count?.key, "speakers:run");
  assert.equal(activity.fraction, 0);
  // After approved names, the scan's last count is not the requests'.
  activity = estimateActivity(flow(run("preparing", 10), true));
  assert.equal(activity.count, undefined);
  activity = estimateActivity(flow(run("collect", 3)));
  assert.equal(activity.count?.key, "requests:run");
  assert.equal(activity.fraction, 0.3);
});
