import assert from "node:assert/strict";
import test from "node:test";
import { historyOutcome } from "../app/src/features/guided/historyView.ts";
import { textLocation } from "../app/src/features/guided/textLocation.ts";
import type { GuidedState, Job, RunPayload } from "../app/src/api/contracts.ts";
import {
  requestRows,
  requestBatches,
  requestBatchOutcome,
  payloadForBatch,
  requestOutcome,
} from "../app/src/features/guided/requestView.ts";
import {
  completeForSelection,
  estimateFollowup,
  eventTaskFiles,
  preparationFollowup,
  estimateRequestCount,
  filePreviewRun,
  fileRun,
  fileMetricRun,
  fileLines,
  fileStatus,
  phaseRun,
  settledWithoutRequests,
  translationTaskComplete,
  unsettledBatches,
  needsSubmissionReview,
  unconfirmedSubmission,
  canResumeRun,
  requestContext,
  translatedLines,
  translationStopLabel,
  observedRun,
  groupedRequests,
  requestAttempt,
} from "../app/src/features/guided/translationView.ts";

test("clarification selection groups stable receipt indices and keeps each attempt's response and usage", () => {
  // A retry must not create another source selection or overwrite the original
  // while a late receipt changes the group's latest status.
  const original = {
    index: 0,
    state: "rejected",
    file: "Items.json",
    sourceItems: 1,
  };
  const other = {
    index: 1,
    state: "validated",
    file: "Other.json",
    sourceItems: 1,
  };
  const retry = {
    ...original,
    index: 2,
    clarificationOf: 0,
    state: "submitted",
  };
  const rows = [original, other, retry];
  assert.deepEqual(
    groupedRequests(rows).map((row) => [
      row.number,
      row.index,
      row.indices,
      row.state,
    ]),
    [
      [1, 0, [0, 2], "submitted"],
      [2, 1, [1], "validated"],
    ],
  );
  assert.equal(original.state, "rejected");
  // A validation retry resends the same lines; they count once.
  assert.deepEqual(
    groupedRequests([
      original,
      other,
      { ...retry, clarificationOf: undefined, retryOf: 0 },
    ]).map((row) => [row.indices, row.sourceItems]),
    [
      [[0, 2], 1],
      [[1], 1],
    ],
  );
  assert.equal(
    groupedRequests([original, other, { ...retry, file: "Foreign.json" }])
      .length,
    3,
  );
  assert.equal(
    groupedRequests([original, other, { ...retry, clarificationOf: 99 }])
      .length,
    3,
  );
  assert.equal(
    groupedRequests([original, other, { ...retry, state: "validated" }])[0]
      .state,
    "validated",
  );
  const first = {
    index: 0,
    state: "rejected",
    response: "Original refusal",
    usage: { input_tokens: 3 },
  } as RunPayload;
  const last = {
    index: 2,
    state: "validated",
    response: "Translation",
    usage: { input_tokens: 5 },
  } as RunPayload;
  const payload: RunPayload = {
    ...first,
    responseAttempts: [
      { kind: "original", response: first.response, payload: first },
      { kind: "clarification", response: last.response, payload: last },
    ],
  };
  assert.equal(requestAttempt(payload, 0), first);
  assert.equal(requestAttempt(payload, 1), last);
  assert.equal(requestAttempt(first, 0), first);
  // Attempt selection must show the failed original independently of a passed retry.
  assert.equal(requestOutcome(requestAttempt(payload, 0)).group, "failed");
  assert.equal(requestOutcome(requestAttempt(payload, 1)).group, "finished");
});

test("request choices identify finished receipts and retain file groups, previews and receipt indices", () => {
  const rows = requestRows([
    {
      index: 0,
      file: "CommonEvents.json",
      state: "submitted",
      sourceItems: 1,
      preview: "The locked door",
      providerFinished: true,
    },
    {
      index: 1,
      file: "Map001.json",
      state: "received",
      sourceItems: 1,
      preview: "A silver key",
    },
    {
      index: 2,
      file: "CommonEvents.json",
      state: "submitted",
      sourceItems: 2,
      preview: "The open door",
    },
    { index: 3, file: "Map001.json", state: "queued", sourceItems: 1 },
    { index: 4, file: "Map001.json", state: "rejected", sourceItems: 1 },
    { index: 5, file: "CommonEvents.json", state: "uncertain", sourceItems: 1 },
    {
      index: 6,
      file: "Map001.json",
      state: "submitted",
      sourceItems: 1,
      clarificationOf: 4,
    },
    { index: 7, file: "Other.json", state: "failed", sourceItems: 1 },
  ]);
  assert.deepEqual(
    rows.map((row) => row.index),
    [0, 2, 5, 1, 3, 4, 7],
  );
  // Receiving a body alone must not display a successful validation outcome.
  assert.deepEqual(
    rows
      .filter((row) => row.outcome.group === "finished")
      .map((row) => row.index),
    [0],
  );
  assert.deepEqual(
    rows
      .filter((row) => row.outcome.group === "failed")
      .map((row) => row.index),
    [7],
  );
  assert.deepEqual(
    rows
      .filter((row) => row.outcome.group === "pending")
      .map((row) => row.index),
    [2, 5, 1, 3, 4],
  );
  assert.equal(rows.find((row) => row.index === 1)?.preview, "A silver key");
  // The latest attempt must not inherit a finished marker from its parent.
  const retry = requestRows([
    { index: 0, state: "submitted", providerFinished: true, sourceItems: 1 },
    { index: 1, state: "submitted", clarificationOf: 0, sourceItems: 1 },
  ]);
  assert.equal(retry[0].outcome.group, "pending");
});

test("batch groups deduplicate linked clarifications while preserving membership and separate replies", () => {
  const process = {
    errors: [],
    requests: [
      {
        index: 0,
        state: "submitted",
        file: "CommonEvents.json",
        sourceItems: 1,
      },
      { index: 1, state: "submitted", file: "Map001.json", sourceItems: 1 },
      {
        index: 2,
        state: "received",
        file: "CommonEvents.json",
        sourceItems: 1,
      },
      { index: 3, state: "queued", file: "CommonEvents.json", sourceItems: 1 },
      { index: 4, state: "uncertain", file: "Map001.json", sourceItems: 1 },
    ],
    batches: [
      {
        id: "original",
        status: "completed",
        total: 2,
        counts: { succeeded: 2 },
        requestIndices: [0, 2],
      },
      {
        id: "retry",
        status: "in_progress",
        total: 1,
        counts: {},
        requestIndices: [2],
        clarification: true,
        originalBatchId: "original",
      },
      {
        id: "other",
        status: "completed",
        total: 1,
        counts: { succeeded: 1 },
        requestIndices: [1],
      },
      { id: "legacy", status: "completed", total: 5, counts: {} },
    ],
  };
  const groups = requestBatches(process, "batch");
  assert.deepEqual(
    groups.map((group) => [group.id, group.rows.map((row) => row.index)]),
    [
      ["original", [0, 2]],
      ["other", [1]],
      ["legacy", []],
      ["unsent", [3]],
      ["unlinked", [4]],
    ],
  );
  assert.deepEqual(
    groups[0].clarifications.map((batch) => batch.id),
    ["retry"],
  );
  assert.equal(groups[0].provider?.total, 2); // A retry does not add another source request.
  const job = {
    id: "run",
    mode: "batch",
    status: "stopped",
    message: "",
    log: [],
  } as Job;
  assert.equal(requestBatchOutcome(groups[0], job)?.active, true);
  assert.equal(requestBatchOutcome(groups[0], job)?.successful, false);
  const complete = {
    ...groups[0],
    clarifications: [
      {
        ...groups[0].clarifications[0],
        status: "completed",
        counts: { succeeded: 1 },
      },
    ],
  };
  assert.equal(requestBatchOutcome(complete, job)?.successful, true);
  const failed = {
    ...complete,
    clarifications: [
      {
        ...complete.clarifications[0],
        status: "failed",
        counts: { succeeded: 0, errored: 1 },
      },
    ],
  };
  assert.equal(requestBatchOutcome(failed, job)?.failed, true);
  // Similar files or overlapping indices cannot link an orphan to a different parent.
  const orphan = requestBatches(
    {
      ...process,
      batches: process.batches.map((batch) =>
        batch.id === "retry" ? { ...batch, originalBatchId: "missing" } : batch,
      ),
    },
    "batch",
  );
  assert.deepEqual(orphan[0].clarifications, []);
  assert.deepEqual(
    orphan[1].rows.map((row) => row.index),
    [2],
  );
  // Counts, same-file requests and missing mappings cannot fill a provider batch.
  assert.equal(
    requestBatches(
      {
        ...process,
        batches: process.batches.map(({ requestIndices, ...batch }) => batch),
      },
      "batch",
    )[0].rows.length,
    0,
  );
  assert.equal(requestBatches(process, "translate").length, 1);
  const original = {
    index: 2,
    state: "rejected",
    response: "Original refusal",
  } as RunPayload;
  const retry = {
    index: 2,
    state: "received",
    response: "Translated reply",
  } as RunPayload;
  const payload = {
    ...retry,
    responseAttempts: [
      {
        kind: "original" as const,
        batchId: "original",
        response: original.response,
        payload: original,
      },
      {
        kind: "clarification" as const,
        batchId: "retry",
        response: retry.response,
        payload: retry,
      },
      {
        kind: "clarification" as const,
        batchId: "other",
        response: "Unrelated response",
      },
    ],
  };
  assert.equal(
    requestAttempt(payloadForBatch(payload, "original"), 0),
    original,
  );
  assert.equal(requestAttempt(payloadForBatch(payload, "retry"), 0), retry);
  const family = payloadForBatch(payload, [
    groups[0].id,
    ...groups[0].clarifications.map((batch) => batch.id),
  ]);
  assert.equal(family.responseAttempts?.length, 2);
  assert.equal(requestAttempt(family, 0), original);
  assert.equal(requestAttempt(family, 1), retry);
  assert.equal(payloadForBatch(payload, "unknown").response, null);
  assert.equal(payloadForBatch(payload), payload);
});

test("a later event-code task cannot inherit completion from map outputs or an old Apply receipt", () => {
  const maps: Job = {
    id: "maps",
    logicalPhase: "dialogue",
    mode: "batch",
    status: "complete",
    message: "",
    log: [],
    files: ["Map001.json", "Map002.json"],
    outputs: { "Map001.json": "hash", "Map002.json": "missing" },
    availableOutputs: ["Map001.json"],
    outputsAvailable: false,
    appliedOutputs: [],
  };
  assert.equal(
    fileStatus("Map001.json", phaseRun([maps], "advanced")).label,
    "Not started",
  );
  assert.equal(
    fileStatus("Map001.json", phaseRun([maps], "dialogue")).label,
    "Ready to apply",
  );
  // A recorded output that is missing cannot be applied.
  assert.equal(fileStatus("Map002.json", maps).label, "Blocked");
  assert.equal(
    fileStatus("Map001.json", { ...maps, partialOutputs: ["Map001.json"] })
      .label,
    "Needs review",
  );
  const rejected = {
    ...maps,
    availableOutputs: ["Map001.json"],
    partialOutputs: ["Map001.json"],
    process: {
      rejected: 2,
      validationIssues: [{ file: "Map001.json", rejected: 2 }],
      errors: [],
    },
  };
  assert.equal(fileStatus("Map001.json", rejected).state, "needs_review");
  assert.equal(fileStatus("Map002.json", rejected).label, "Blocked");
  assert.equal(
    fileStatus("Map001.json", { ...rejected, retiredFiles: ["Map001.json"] })
      .state,
    "not_started",
  );
  assert.equal(
    historyOutcome({ ...rejected, outputs: { "Map001.json": "hash" } }).kind,
    "partial",
  );
  assert.equal(
    fileStatus("Map001.json", { ...maps, retiredFiles: ["Map001.json"] }).label,
    "Not started",
  );
  assert.equal(
    fileStatus("Map001.json", { ...maps, appliedOutputs: ["Map001.json"] })
      .label,
    "Applied",
  );
  const partial = {
    ...maps,
    status: "interrupted",
    availableOutputs: [],
    outputs: {},
    process: {
      requests: [
        { index: 0, file: "Map001.json", state: "uncertain", sourceItems: 1 },
      ],
      errors: [],
    },
  };
  assert.equal(fileStatus("Map001.json", partial).label, "Needs review");
  // An unconfirmed submission must not read as rejected lines.
  assert.notEqual(
    fileStatus("Map001.json", partial).detail,
    fileStatus("Map001.json", rejected).detail,
  );
  // A stopped Live run leaves its unanswered request marked sent; that is
  // unconfirmed too.
  const stopped = {
    ...partial,
    mode: "translate",
    status: "stopped",
    process: {
      ...partial.process,
      requests: [{ ...partial.process.requests[0], state: "submitted" }],
    },
  };
  assert.equal(
    fileStatus("Map001.json", stopped).detail,
    fileStatus("Map001.json", partial).detail,
  );
  // A Live file still being written, such as one with nothing to send, is
  // partial until it finishes but only rejected lines need review meanwhile.
  const writing = {
    ...maps,
    mode: "translate",
    status: "running",
    partialOutputs: ["Map001.json"],
    process: { requests: [], errors: [] },
  };
  assert.equal(fileStatus("Map001.json", writing).label, "Working");
  assert.equal(
    fileStatus("Map001.json", { ...writing, process: rejected.process }).label,
    "Needs review",
  );
  // Requests a run never sent, such as a refused Batch, leave the file untouched.
  const unsent = {
    ...partial,
    status: "failed",
    process: {
      ...partial.process,
      requests: [{ ...partial.process.requests[0], state: "queued" }],
    },
  };
  assert.equal(fileStatus("Map001.json", unsent).state, "not_started");
  // A failed request returned no lines to review, unlike a rejected reply.
  const failedRow = { ...partial.process.requests[0], state: "failed" };
  const failed = {
    ...unsent,
    process: { ...partial.process, requests: [failedRow] },
  };
  assert.equal(fileStatus("Map001.json", failed).state, "not_started");
  assert.equal(
    fileStatus("Map001.json", {
      ...failed,
      process: {
        ...partial.process,
        requests: [failedRow, { ...failedRow, index: 1, state: "rejected" }],
      },
    }).state,
    "needs_review",
  );
  // Legacy dismissal flags no longer hide the latest attempt.
  assert.equal(
    phaseRun(
      [{ ...maps, id: "kept", keptForHistory: true }, partial],
      "dialogue",
    )?.id,
    "kept",
  );
  // A new draft selection must not offer Apply for a different completed scope
  // while the backend snapshot still describes the previous saved selection.
  assert.equal(phaseRun([maps], "dialogue", ["Map003.json"]), undefined);
  assert.equal(phaseRun([maps], "dialogue", []), undefined);
  assert.equal(phaseRun([maps], "dialogue", ["Map001.json"]), maps);
  const complete = { ...maps, scopeComplete: true };
  assert.equal(
    completeForSelection(complete, ["Map002.json", "Map001.json"]),
    true,
  );
  assert.equal(completeForSelection(complete, ["Map001.json"]), false);
  assert.equal(
    completeForSelection(complete, ["Map003.json", "Map004.json"]),
    false,
  );
  assert.equal(completeForSelection(complete, []), false);
});

test("opening a file outside the current selection uses that file's retained requests", () => {
  const previous = {
    id: "actors",
    files: ["Actors.json"],
    status: "complete",
    scopeComplete: true,
  } as Job;
  const current = {
    id: "items",
    files: ["Items.json"],
    status: "complete",
    scopeComplete: true,
  } as Job;
  const estimate = { ...current, id: "estimate", mode: "estimate" };
  assert.equal(
    filePreviewRun("Actors.json", current, estimate, previous),
    previous,
  );
  // A current estimate must take precedence over an older completed output.
  assert.equal(
    filePreviewRun("Items.json", current, estimate, previous),
    estimate,
  );
  assert.equal(
    filePreviewRun(
      "Items.json",
      { ...current, status: "running" },
      estimate,
      previous,
    )?.mode,
    current.mode,
  );
  assert.equal(
    filePreviewRun("Items.json", current, estimate, previous, false),
    current,
  );
  assert.equal(
    filePreviewRun(
      "Items.json",
      { ...current, scopeComplete: false, status: "failed" },
      estimate,
      previous,
    ),
    estimate,
  );
  assert.equal(
    filePreviewRun("Unknown.json", current, estimate, previous),
    undefined,
  );
  assert.equal(
    filePreviewRun("Items.json", previous, estimate, current, false),
    current,
  );
  assert.equal(
    filePreviewRun("Items.json", previous, estimate, undefined, false),
    estimate,
  );
});

// Clearing selection or finishing in separate runs must not erase task progress;
// completing only a selected subset must not certify the entire file group.
test("main-text tasks combine verified files across runs independently of selection", () => {
  const items: Job = {
    id: "items",
    logicalPhase: "database",
    mode: "batch",
    status: "complete",
    message: "",
    log: [],
    files: ["Items.json"],
    outputs: { "Items.json": "hash" },
    availableOutputs: ["Items.json"],
    appliedOutputs: ["Items.json"],
  };
  const actors = {
    ...items,
    id: "actors",
    keptForHistory: true,
    files: ["Actors.json"],
    outputs: { "Actors.json": "hash" },
    availableOutputs: ["Actors.json"],
    appliedOutputs: [],
  };
  const empty = {
    ...items,
    id: "empty",
    files: ["Armors.json"],
    outputs: {},
    availableOutputs: [],
    process: { noRequestFiles: ["Armors.json"], errors: [] },
  };
  const state = {
    files: [
      { name: "Items.json", group: "database" },
      { name: "Actors.json", group: "database" },
      { name: "Armors.json", group: "database" },
      { name: "Map001.json", group: "dialogue" },
    ],
    runs: [empty, actors, items],
    sourceStatus: { changed: [], ready: [] },
    preferences: { values: { selected: [] } },
  } as unknown as GuidedState;
  for (const selected of [
    [],
    ["Items.json"],
    ["Items.json", "Actors.json", "Armors.json"],
    ["Map001.json"],
  ]) {
    state.preferences.values.selected = selected;
    assert.equal(translationTaskComplete(state, "database"), true);
    assert.equal(translationTaskComplete(state, "dialogue"), false);
  }
  assert.equal(
    translationTaskComplete({ ...state, runs: [empty, items] }, "database"),
    false,
  );
  // A closed estimate without requests completes a resynced file that has no
  // run; only an older, idle attempt may coexist with that result.
  const checked = "2026-10-05T12:00:00+00:00";
  const settled = {
    ...state,
    runs: [actors, items],
    sourceStatus: {
      changed: [],
      ready: [],
      noRequests: { database: { "Armors.json": checked } },
    },
  } as unknown as GuidedState;
  assert.equal(translationTaskComplete(settled, "database"), true);
  assert.equal(
    fileStatus(
      "Armors.json",
      undefined,
      settledWithoutRequests(settled, "database", "Armors.json"),
    ).label,
    "Ready to apply",
  );
  const armors = { ...empty, id: "armors", process: { errors: [] } };
  for (const [created, status, complete] of [
    ["2026-10-05T11:00:00+00:00", "failed", true],
    ["2026-10-05T11:00:00+00:00", "running", false],
    ["2026-10-05T13:00:00+00:00", "failed", false],
  ] as const)
    assert.equal(
      translationTaskComplete(
        {
          ...settled,
          runs: [{ ...armors, created, status }, actors, items],
        },
        "database",
      ),
      complete,
      `${status} attempt at ${created}`,
    );
  assert.equal(
    translationTaskComplete(
      {
        ...settled,
        sourceStatus: {
          ...settled.sourceStatus,
          noRequests: { advanced: { "Armors.json": checked } },
        },
      },
      "database",
    ),
    false,
  );
  assert.equal(
    translationTaskComplete({ ...state, files: [] }, "database"),
    false,
  );
  assert.equal(
    translationTaskComplete(
      { ...state, runs: [{ ...items, mode: "estimate" }, ...state.runs] },
      "database",
    ),
    true,
  );
  assert.equal(
    translationTaskComplete(
      {
        ...state,
        runs: [actors, items, { ...empty, process: { errors: [] } }],
      },
      "database",
    ),
    false,
  );
  assert.equal(
    translationTaskComplete(
      {
        ...state,
        runs: [
          actors,
          items,
          { ...empty, outputs: { "Armors.json": "missing" } },
        ],
      },
      "database",
    ),
    false,
  );
  const maps = {
    ...items,
    id: "maps",
    logicalPhase: "dialogue" as const,
    files: ["Map001.json"],
    outputs: { "Map001.json": "hash" },
    availableOutputs: ["Map001.json"],
  };
  assert.equal(
    translationTaskComplete(
      { ...state, runs: [maps, ...state.runs] },
      "dialogue",
    ),
    true,
  );
  assert.equal(
    translationTaskComplete(
      {
        ...state,
        runs: [maps, ...state.runs].map((run) => ({
          ...run,
          logicalPhase: "advanced",
        })),
      },
      "dialogue",
    ),
    false,
  );
  // Event-code tasks keep finished files when one is re-run or the selection
  // is cleared, and a newly selected file still needs its run.
  const events = {
    ...maps,
    id: "events",
    logicalPhase: "advanced" as const,
    files: ["Map001.json", "Map002.json"],
    outputs: { "Map001.json": "hash", "Map002.json": "hash" },
    availableOutputs: ["Map001.json", "Map002.json"],
  };
  const rerun = { ...maps, id: "rerun", logicalPhase: "advanced" as const };
  const eventState = {
    ...state,
    files: [
      ...state.files,
      { name: "Map002.json", group: "dialogue" },
      { name: "Map003.json", group: "dialogue" },
    ],
    runs: [rerun, events],
  } as unknown as GuidedState;
  const eventsDone = (selected: string[]) =>
    translationTaskComplete(
      eventState,
      "advanced",
      eventTaskFiles(eventState, "advanced", selected),
    );
  assert.equal(eventsDone(["Map001.json"]), true);
  assert.equal(eventsDone([]), true);
  assert.equal(eventsDone(["Map003.json"]), false);
  assert.equal(
    translationTaskComplete({ ...eventState, runs: [rerun] }, "advanced", [
      "Map001.json",
      "Map002.json",
    ]),
    false,
  );
});

// Historical success cannot hide unfinished replacement work, unavailable output,
// or a source reload, including when the active worker is an older attempt.
test("main-text completion respects current file ownership and output validity", () => {
  const saved: Job = {
    id: "saved",
    logicalPhase: "database",
    mode: "translate",
    status: "complete",
    message: "",
    log: [],
    files: ["Items.json"],
    outputs: { "Items.json": "hash" },
    availableOutputs: ["Items.json"],
    appliedOutputs: ["Items.json"],
  };
  const state = {
    files: [{ name: "Items.json", group: "database" }],
    runs: [saved],
    sourceStatus: { changed: [], ready: [] },
  } as Pick<GuidedState, "files" | "runs" | "sourceStatus">;
  for (const patch of [
    { status: "running" },
    { status: "waiting" },
    { temporary: true },
    { partialOutputs: ["Items.json"] },
    { availableOutputs: [] },
    {
      status: "failed",
      outputs: {},
      availableOutputs: [],
      keptForHistory: true,
    },
    { mode: "batch", status: "interrupted", phase: "poll_status" },
  ]) {
    assert.equal(
      translationTaskComplete(
        { ...state, runs: [{ ...saved, ...patch, id: "new" }, saved] },
        "database",
      ),
      false,
      JSON.stringify(patch),
    );
  }
  assert.equal(
    translationTaskComplete(
      {
        ...state,
        runs: [saved, { ...saved, id: "resumed", status: "running" }],
      },
      "database",
    ),
    false,
  );
  assert.equal(
    translationTaskComplete(
      {
        ...state,
        sourceStatus: { ...state.sourceStatus, changed: ["Items.json"] },
      },
      "database",
    ),
    false,
  );
  assert.equal(
    translationTaskComplete(
      {
        ...state,
        sourceStatus: { ...state.sourceStatus, retired: [saved.id] },
      },
      "database",
    ),
    false,
  );
  assert.equal(
    translationTaskComplete(
      { ...state, runs: [{ ...saved, retiredFiles: ["Items.json"] }] },
      "database",
    ),
    false,
  );
});

test("request comparisons reject misaligned or unvalidated Live responses and mismatched Batch keys", () => {
  const payload = {
    source: { Line1: "薬", Line2: "毒" },
    state: "validated",
    response: ["Medicine", "Poison"],
  } as RunPayload;
  assert.deepEqual(translatedLines(payload), {
    Line1: "Medicine",
    Line2: "Poison",
  });
  assert.equal(
    translatedLines({ ...payload, response: ["Wrong request"] }),
    null,
  );
  assert.equal(translatedLines({ ...payload, state: "received" }), null);
  assert.deepEqual(
    translatedLines({
      ...payload,
      state: "received",
      response: { text: '{"Line2":"Poison","Line1":"Medicine"}' },
    }),
    { Line2: "Poison", Line1: "Medicine" },
  );
  assert.equal(
    translatedLines({
      ...payload,
      response: { text: '{"Line1":"Medicine","Line3":"Poison"}' },
    }),
    null,
  );
  assert.equal(
    translatedLines({ ...payload, response: { text: "Unstructured reply" } }),
    null,
  );
  assert.equal(
    translatedLines({
      ...payload,
      state: "rejected",
      response: { text: '{"Line1":"Medicine","Line2":"Poison"}' },
    }),
    null,
  );
  assert.equal(
    translatedLines({
      ...payload,
      state: "unused",
      response: { text: '{"Line1":"Medicine","Line2":"Poison"}' },
    }),
    null,
  );
  const raw = {
    text: '{"translations":["__PROTECTED_0__Medicine","Poison"]}',
    refusal: null,
  };
  assert.deepEqual(
    translatedLines({
      ...payload,
      response: raw,
      translations: ["\\C[1]Medicine", "Poison"],
    }),
    { Line1: "\\C[1]Medicine", Line2: "Poison" },
  );
  assert.equal(
    translatedLines({
      ...payload,
      state: "received",
      response: raw,
      translations: null,
    }),
    null,
  );
});

// Prevent dumping the static prompt into the context preview or substituting
// current glossary entries for the specific request's retained matches.
test("context preview separates matched guidance from static prompts and translatable source", () => {
  const dynamic =
    "Here are glossary entries with the approved spelling and translation.\n# Speakers\nアスター (Aster)";
  const staticPrompt =
    "Rules with an example\n```json\n{}\n```\nDo not remove control codes.";
  const source = { Line1: "薬" };
  const messages = [
    { role: "system", content: "```\n" + staticPrompt + "\n```\n\n" + dynamic },
    {
      role: "user",
      content:
        "Preceding Japanese Source Context (untranslated):\nUse for scene context.\n```\n前の台詞\n```",
    },
    {
      role: "user",
      content: "Request Instructions:\n```\nTranslate item names.\n```",
    },
    { role: "user", content: '```json\n{"Line1":"薬"}\n```' },
  ];
  const payload = { source, messages } as unknown as RunPayload;
  const sections = requestContext(payload);
  assert.deepEqual(
    sections.map((section) => section.text),
    [dynamic, "前の台詞", "Translate item names."],
  );
  assert.equal(sections[2].notes, true);
  assert.deepEqual(
    requestContext({
      ...payload,
      messages: messages.slice(1),
      system: [
        { type: "text", text: staticPrompt },
        { type: "text", text: dynamic },
      ],
    }),
    sections,
  );
  assert.deepEqual(
    requestContext({
      ...payload,
      messages: [{ role: "system", content: staticPrompt }],
      context: null,
    }),
    [],
  );
  assert.deepEqual(
    requestContext({
      ...payload,
      context: {
        source_items: ["Exact saved scene"],
        instructions: ["Exact saved instructions"],
      },
    }).map((section) => section.text),
    [dynamic, "Exact saved scene", "Exact saved instructions"],
  );
});

// Protect stale overlapping failures becoming current after an estimate, a
// selection change, while unresolved receipts remain actionable.
test("new attempts supersede historical warnings without releasing submission protections", () => {
  const old = {
    id: "old",
    created: "2020-01-01",
    updated: "2030-01-01",
    mode: "batch",
    logicalPhase: "database",
    files: ["Items.json", "Actors.json"],
    status: "failed",
    phase: "poll",
    process: {
      failed: 82,
      retryBlocked: false,
      requests: [
        { index: 0, file: "Items.json", state: "failed", sourceItems: 1 },
      ],
    },
  } as Job;
  const next = {
    ...old,
    id: "next",
    created: "2026-01-01",
    files: ["Actors.json"],
  };
  assert.equal(phaseRun([old, next], "database", ["Items.json"]), undefined);
  assert.equal(phaseRun([old, next], "database", ["Actors.json"]), next);
  assert.equal(
    phaseRun([{ ...next, mode: "estimate" }, old], "database"),
    undefined,
  );
  assert.equal(
    phaseRun([{ ...next, keptForHistory: true }, old], "database")?.id,
    next.id,
  );
  assert.equal(fileStatus("Items.json", old).label, "Not started");
  assert.equal(needsSubmissionReview(old), false);
  assert.equal(canResumeRun(old), false);
  assert.equal(
    canResumeRun({ ...old, mode: "estimate", phase: "prepare" }),
    false,
  );
  const unresolved = {
    ...old,
    keptForHistory: true,
    process: { ...old.process!, retryBlocked: true },
  };
  assert.equal(needsSubmissionReview(unresolved), true);
  assert.equal(canResumeRun(unresolved), false);
  const resumed = { ...unresolved, status: "running" };
  assert.equal(phaseRun([next, resumed], "database"), resumed);
  // Unsettled work stays visible regardless of a Batch's successful row count.
  const failedBatch = {
    id: "paid",
    status: "failed",
    counts: { succeeded: 0 },
  };
  const terminalFailure = {
    ...unresolved,
    process: { ...unresolved.process, batches: [failedBatch] },
  };
  assert.deepEqual(unsettledBatches([terminalFailure], ["Items.json"]), [
    terminalFailure,
  ]);
  assert.equal(needsSubmissionReview(terminalFailure), true);
  // A Batch the provider confirmed stays protected without being reported as
  // possibly unsent; doubt needs an unconfirmed request after sending ended.
  const atProvider = {
    ...terminalFailure,
    status: "running",
    process: {
      ...terminalFailure.process,
      uncertain: 0,
      batches: [{ ...failedBatch, status: "in_progress" }],
    },
  } as Job;
  assert.equal(unsettledBatches([atProvider], ["Items.json"]).length, 1);
  assert.equal(unconfirmedSubmission(atProvider), false);
  const unconfirmed = {
    ...terminalFailure,
    process: { ...terminalFailure.process, uncertain: 1 },
  } as Job;
  assert.equal(unconfirmedSubmission(unconfirmed), true);
  assert.equal(
    unconfirmedSubmission({ ...unconfirmed, status: "running" }),
    false,
  );
  for (const guarded of [
    unresolved,
    { ...terminalFailure, status: "running" },
    {
      ...terminalFailure,
      process: {
        ...terminalFailure.process,
        monitoring: { state: "collecting" },
      },
    },
    ...[
      { ...failedBatch, status: "in_progress" },
      { ...failedBatch, counts: {} },
      { ...failedBatch, counts: { succeeded: 1 } },
    ].map((batch) => ({
      ...terminalFailure,
      process: { ...terminalFailure.process, batches: [batch] },
    })),
  ])
    assert.equal(unsettledBatches([guarded as Job], ["Items.json"]).length, 1);
});

// History must not turn local estimates, absent receipts or a stopped/failed
// worker with partial output into a successful translated-file claim.
test("history outcomes distinguish verified output from completed attempts and unresolved submissions", () => {
  const done = {
    id: "history",
    status: "complete",
    mode: "batch",
    files: ["Items.json"],
    process: { prepared: 0, received: 0, errors: [] },
  } as Job;
  assert.equal(historyOutcome(done).kind, "empty");
  assert.equal(historyOutcome({ ...done, mode: "estimate" }).kind, "estimate");
  const recorded = { ...done, outputs: { "Items.json": "hash" } };
  assert.equal(historyOutcome(recorded).kind, "finished");
  assert.equal(
    historyOutcome({ ...recorded, availableOutputs: [] }).kind,
    "missing",
  );
  const verified = { ...recorded, availableOutputs: ["Items.json"] };
  assert.equal(historyOutcome(verified).kind, "saved");
  assert.equal(
    historyOutcome({ ...verified, partialOutputs: ["Items.json"] }).kind,
    "partial",
  );
  assert.equal(
    historyOutcome({ ...verified, status: "failed" }).kind,
    "failed",
  );
  assert.equal(
    historyOutcome({
      ...verified,
      status: "stopped",
      keptForHistory: true,
      process: { ...done.process!, retryBlocked: true },
    }).kind,
    "review",
  );
  assert.equal(
    historyOutcome({
      ...verified,
      status: "waiting",
      approval: { token: "fixture", kind: "batch", detail: {} },
    }).kind,
    "approval",
  );
});

// An old run can lack request evidence while its estimate still requires paid
// work. Conversely, a finished zero-request estimate must have an explicit result.
test("translation followup uses the matching estimate count and exits for terminal failures", () => {
  const job = {
    id: "new-estimate",
    mode: "estimate",
    status: "complete",
    estimate: { requests: 3 },
    process: { prepared: 0, errors: [] },
  } as Job;
  const quote = { job, current: true };
  assert.equal(estimateFollowup(job.id, quote, [job], false).kind, "review");
  assert.equal(
    estimateRequestCount({ ...job, estimate: { request_count: 2 } }),
    2,
  );
  assert.equal(
    estimateFollowup(
      job.id,
      { ...quote, job: { ...job, estimate: { requests: 0 } } },
      [job],
      false,
    ).kind,
    "empty",
  );
  assert.equal(
    estimateFollowup(
      job.id,
      { ...quote, job: { ...job, estimate: {} } },
      [job],
      false,
    ).kind,
    "review",
  );
  // Live estimates report no request count; finding no source text is empty.
  assert.equal(
    estimateFollowup(
      job.id,
      { ...quote, job: { ...job, estimate: {}, nothingToTranslate: true } },
      [job],
      false,
    ).kind,
    "empty",
  );
  assert.equal(
    estimateFollowup(
      job.id,
      { ...quote, job: { ...job, status: "running" } },
      [job],
      false,
    ).kind,
    "waiting",
  );
  assert.equal(
    estimateFollowup(job.id, { ...quote, current: false }, [job], false).kind,
    "stale",
  );
  assert.equal(estimateFollowup(job.id, quote, [job], true).kind, "stale");
  assert.equal(
    estimateFollowup(
      job.id,
      { job: { ...job, id: "other" }, current: true },
      [job],
      false,
    ).kind,
    "stale",
  );
  // A failed/stopped run remains visible even if quote calculation can no
  // longer produce a current entry. It must not leave Translate spinning.
  for (const status of ["failed", "stopped", "interrupted", "canceled"]) {
    assert.equal(
      estimateFollowup(job.id, undefined, [{ ...job, status }], false).kind,
      "failed",
    );
  }
  assert.equal(estimateFollowup(job.id, undefined, [], false).kind, "waiting");
  // A delayed speaker approval must not reopen after it was answered. A
  // distinct Batch approval retains the verified name result for its review.
  const names = {
    ...job,
    id: "paid",
    mode: "batch",
    status: "waiting",
    approval: { token: "names", kind: "speakers", detail: {} },
  } as Job;
  assert.deepEqual(preparationFollowup(names.id, [names], "names"), {
    kind: "waiting",
  });
  const translated = {
    ...names,
    approval: { token: "maps", kind: "batch", detail: {} },
    nameTranslation: {
      state: "saved",
      count: 1,
      rows: [{ source: "回想部屋", translation: "Recollection Room" }],
    },
  } as Job;
  assert.equal(
    preparationFollowup(names.id, [translated], "names").kind,
    "review",
  );
  assert.equal(
    preparationFollowup(names.id, [translated], "names").job?.nameTranslation,
    translated.nameTranslation,
  );
  assert.equal(
    preparationFollowup(
      names.id,
      [{ ...translated, approval: undefined, status: "failed" }],
      "names",
    ).kind,
    "failed",
  );
});

// Hiding preparation controls must not remove the exit from paid execution or
// confuse stopping local monitoring with canceling a submitted provider Batch.
test("translation stop controls distinguish preparation, approval and running work", () => {
  const job = {
    id: "run",
    mode: "batch",
    status: "running",
    log: [],
    message: "",
  } as Job;
  assert.equal(translationStopLabel(undefined), null);
  const temporary = {
    ...job,
    temporary: true,
    status: "stopped",
    files: ["Items.json"],
  };
  assert.equal(canResumeRun(temporary), false);
  assert.equal(fileStatus("Items.json", temporary).label, "Not started");
  assert.equal(
    fileStatus("Items.json", { ...temporary, status: "failed" }).label,
    "Not started",
  );
  assert.equal(translationStopLabel({ ...job, mode: "estimate" }), null);
  for (const phase of [
    undefined,
    "preparing",
    "collect",
    "collect_done",
    "submit",
  ]) {
    assert.equal(
      translationStopLabel({
        ...job,
        phase,
        process: { submitted: 0, errors: [] },
      }),
      null,
    );
  }
  assert.equal(
    translationStopLabel({ ...job, process: { submitted: 1, errors: [] } }),
    null,
  );
  assert.equal(translationStopLabel({ ...job, phase: "poll_status" }), null);
  assert.equal(
    translationStopLabel({
      ...job,
      phase: "consume",
      process: { submitted: 1, errors: [] },
    }),
    null,
  );
  assert.equal(
    translationStopLabel({ ...job, mode: "translate" }),
    "Stop translation",
  );
  for (const mode of ["batch", "translate"]) {
    assert.equal(
      translationStopLabel({
        ...job,
        mode,
        status: "waiting",
        approval: { token: "review", kind: "batch", detail: {} },
      }),
      null,
    );
    for (const status of [
      "complete",
      "failed",
      "stopped",
      "interrupted",
      "canceled",
    ]) {
      assert.equal(
        translationStopLabel({ ...job, mode, status, phase: "poll" }),
        null,
      );
    }
  }
});

// An earlier checkpoint must not freeze the rows at Saved while a provider is
// working. A resumed older run also needs to displace a newer finished attempt.
test("file metrics survive unchanged passes and advance only with changed output", () => {
  const old = {
    id: "old",
    logicalPhase: "database",
    mode: "batch",
    status: "complete",
    files: ["Items.json"],
    changedOutputs: ["Items.json"],
    process: {
      errors: [],
      fileMetrics: { "Items.json": { cost: 0.125, seconds: 12.5 } },
    },
  } as Job;
  const skipped = {
    ...old,
    id: "skipped",
    status: "running",
    changedOutputs: [],
    process: { errors: [], noRequestFiles: ["Items.json"], fileMetrics: {} },
  };
  assert.equal(fileMetricRun([skipped, old], "database", "Items.json"), old);
  const unchanged = {
    ...skipped,
    status: "complete",
    process: {
      errors: [],
      fileMetrics: { "Items.json": { cost: 0, seconds: 0.1 } },
    },
  };
  assert.equal(fileMetricRun([unchanged, old], "database", "Items.json"), old);
  const changed = { ...unchanged, changedOutputs: ["Items.json"] };
  assert.equal(
    fileMetricRun([changed, old], "database", "Items.json"),
    changed,
  );
  const unrecorded = { ...changed, process: { errors: [] } };
  assert.equal(
    fileMetricRun([unrecorded, old], "database", "Items.json"),
    unrecorded,
  );
  assert.equal(
    fileMetricRun([old], "database", "Items.json", [old.id]),
    undefined,
  );
  assert.equal(
    fileMetricRun(
      [{ ...old, retiredFiles: ["Items.json"] }],
      "database",
      "Items.json",
    ),
    undefined,
  );
  assert.equal(fileMetricRun([old], "dialogue", "Items.json"), undefined);
  const resumed = { ...old, status: "running" };
  assert.equal(
    fileMetricRun([changed, resumed], "database", "Items.json"),
    resumed,
  );
  assert.equal(
    fileMetricRun(
      [{ ...skipped, changedOutputs: undefined }, old],
      "database",
      "Items.json",
    ),
    old,
  );
  assert.equal(
    fileMetricRun(
      [{ ...changed, mode: "estimate" }, { ...changed, temporary: true }, old],
      "database",
      "Items.json",
    ),
    old,
  );
});

test("file status follows active and automatically monitored Batch work before retained outputs", () => {
  const checkpoint = {
    id: "batch",
    logicalPhase: "database",
    mode: "batch",
    status: "running",
    phase: "poll_status",
    files: ["Items.json"],
    outputs: { "Items.json": "saved" },
    availableOutputs: ["Items.json"],
    partialOutputs: ["Items.json"],
    process: {
      retryBlocked: true,
      requests: [
        { index: 0, file: "Items.json", state: "submitted", sourceItems: 1 },
      ],
      batches: [
        { id: "paid", status: "in_progress", requestIndices: [0], counts: {} },
      ],
      errors: [],
    },
    log: [],
    message: "",
  } as Job;
  assert.equal(fileStatus("Items.json", checkpoint).label, "Working");
  // Merging activity labels must not animate an approval wait as running work,
  // or hide provider activity just because the local worker has stopped.
  const approval: Job = {
    ...checkpoint,
    temporary: true,
    status: "waiting",
    approval: { token: "quote", kind: "batch", detail: {} },
  };
  assert.equal(fileStatus("Items.json", approval).pending, false);
  assert.equal(
    fileStatus("Items.json", { ...approval, approval: undefined }).pending,
    true,
  );
  assert.equal(
    fileStatus("Items.json", { ...checkpoint, status: "stopped" }).pending,
    true,
  );
  const withSkipped = {
    ...checkpoint,
    files: ["Items.json", "Armors.json"],
    process: { ...checkpoint.process!, noRequestFiles: ["Armors.json"] },
  };
  assert.equal(fileStatus("Armors.json", withSkipped).label, "Ready to apply");
  assert.equal(
    fileStatus("Armors.json", {
      ...withSkipped,
      temporary: true,
      status: "waiting",
    }).label,
    "Ready to apply",
  );
  assert.equal(
    fileStatus("Armors.json", {
      ...withSkipped,
      status: "complete",
      availableOutputs: ["Armors.json"],
    }).label,
    "Ready to apply",
  );
  assert.notEqual(
    fileStatus("Armors.json", { ...withSkipped, mode: "translate" }).label,
    "Ready to apply",
  );
  const received = {
    ...checkpoint,
    process: {
      ...checkpoint.process!,
      requests: [
        { index: 0, file: "Items.json", state: "received", sourceItems: 1 },
      ],
    },
  };
  assert.equal(fileStatus("Items.json", received).label, "Needs review");
  assert.equal(
    fileStatus("Items.json", { ...received, availableOutputs: [] }).label,
    "Blocked",
  );
  assert.equal(
    fileStatus("Items.json", { ...received, phase: "consume" }).label,
    "Working",
  );
  assert.equal(
    fileStatus("Items.json", {
      ...received,
      phase: "consume",
      partialOutputs: [],
    }).label,
    "Ready to apply",
  );
  assert.equal(
    fileStatus("Items.json", { ...checkpoint, status: "stopped" }).label,
    "Working",
  );
  assert.equal(
    fileStatus("Items.json", {
      ...checkpoint,
      status: "complete",
      partialOutputs: [],
    }).label,
    "Ready to apply",
  );
  assert.equal(
    fileStatus("Items.json", { ...checkpoint, mode: "translate" }).label,
    "Working",
  );
  assert.equal(
    fileStatus("Items.json", { ...checkpoint, process: { errors: [] } }).label,
    "Needs review",
  );
  const completed = {
    ...checkpoint,
    id: "newer",
    status: "complete",
    partialOutputs: [],
  };
  assert.equal(
    fileRun([completed, checkpoint], "database", "Items.json"),
    checkpoint,
  );
  assert.equal(
    fileRun([completed, checkpoint], "dialogue", "Items.json"),
    undefined,
  );
  assert.equal(
    fileRun([completed, checkpoint], "database", "Items.json", [checkpoint.id]),
    completed,
  );
  const stopped = { ...checkpoint, status: "stopped" };
  assert.deepEqual(
    unsettledBatches(
      [{ ...completed, mode: "estimate" }, stopped],
      ["Items.json"],
    ),
    [stopped],
  );
  assert.deepEqual(unsettledBatches([stopped], ["Actors.json"]), []);
  const providerFinished = {
    ...stopped,
    process: {
      errors: [],
      retryBlocked: false,
      resultsCollected: true,
      batches: [{ id: "paid", status: "completed", counts: {} }],
    },
  };
  assert.equal(canResumeRun(providerFinished), false);
  assert.equal(
    canResumeRun({
      ...providerFinished,
      status: "failed",
      process: {
        ...providerFinished.process,
        resultsCollected: false,
        failed: 12,
      },
    }),
    false,
  );
  assert.deepEqual(unsettledBatches([providerFinished], ["Items.json"]), [
    providerFinished,
  ]);
  assert.deepEqual(
    unsettledBatches(
      [{ ...providerFinished, phase: "consume", status: "failed" }],
      ["Items.json"],
    ),
    [],
  );
  assert.deepEqual(unsettledBatches([checkpoint], ["Actors.json"]), []);
  assert.deepEqual(
    unsettledBatches(
      [{ ...checkpoint, retiredFiles: ["Items.json"] }],
      ["Items.json"],
    ),
    [],
  );
  const monitoring = {
    ...stopped,
    process: {
      ...stopped.process!,
      monitoring: { state: "collecting" as const, message: "" },
    },
  };
  assert.equal(fileStatus("Items.json", monitoring).label, "Working");
  assert.equal(canResumeRun(monitoring), false);
  assert.equal(
    fileStatus("Items.json", {
      ...monitoring,
      process: {
        ...monitoring.process,
        monitoring: { state: "error", message: "Retrying" },
      },
    }).label,
    "Working",
  );
  // A run-wide refresh must not turn saved, failed, untouched or unsent files
  // into provider work. Monitor failures likewise cannot mark each file broken.
  const mixed: Job = {
    ...checkpoint,
    files: [
      "Items.json",
      "Saved.json",
      "Partial.json",
      "Failed.json",
      "Queued.json",
      "Empty.json",
      "Untouched.json",
      "Missing.json",
    ],
    outputs: {
      "Saved.json": "hash",
      "Partial.json": "hash",
      "Missing.json": "missing",
    },
    availableOutputs: ["Saved.json", "Partial.json"],
    partialOutputs: ["Partial.json"],
    process: {
      errors: [],
      batches: checkpoint.process!.batches,
      noRequestFiles: ["Empty.json", "Missing.json"],
      requests: [
        ...checkpoint.process!.requests!,
        { index: 1, file: "Saved.json", state: "saved", sourceItems: 1 },
        { index: 2, file: "Partial.json", state: "rejected", sourceItems: 1 },
        { index: 3, file: "Failed.json", state: "failed", sourceItems: 1 },
        { index: 4, file: "Queued.json", state: "queued", sourceItems: 1 },
        { index: 5, file: "Partial.json", state: "validated", sourceItems: 1 },
      ],
      validationIssues: [{ file: "Partial.json", rejected: 1 }],
    },
  };
  const expected = mixed.files!.map((name) => fileStatus(name, mixed));
  const beforeRefresh = { ...mixed, status: "interrupted" };
  for (const state of [
    "monitoring",
    "collecting",
    "error",
    "save_error",
    "blocked",
  ] as const) {
    const refreshed = {
      ...mixed,
      process: {
        ...mixed.process!,
        monitoring: { state, message: "Checking this run" },
      },
    };
    assert.deepEqual(
      mixed.files!.map((name) => fileStatus(name, refreshed)),
      expected,
    );
    for (const name of [
      "Saved.json",
      "Partial.json",
      "Failed.json",
      "Empty.json",
      "Untouched.json",
      "Missing.json",
    ])
      assert.deepEqual(
        fileStatus(name, refreshed),
        fileStatus(name, beforeRefresh),
      );
  }
  assert.deepEqual(
    expected.map((status) => status.state),
    [
      "working",
      "ready",
      "needs_review",
      "not_started",
      "working",
      "ready",
      "not_started",
      "blocked",
    ],
  );
  // The observer can report monitor activity as a running run. It must not
  // turn dormant requests into queued work or displace a newer file owner.
  const dormant = { ...mixed, status: "failed", workerStatus: "failed" };
  const stable = mixed.files!.map((name) => fileStatus(name, dormant));
  for (const state of [
    "monitoring",
    "collecting",
    "error",
    "save_error",
    "blocked",
  ] as const) {
    const observed = {
      ...dormant,
      status: "running",
      process: {
        ...dormant.process!,
        monitoring: { state, message: "Checking this run" },
      },
    };
    assert.deepEqual(
      mixed.files!.map((name) => fileStatus(name, observed)),
      stable,
    );
    assert.equal(
      fileRun([completed, observed], "database", "Items.json"),
      completed,
    );
    assert.equal(phaseRun([completed, observed], "database"), completed);
    assert.equal(
      fileRun(
        [completed, { ...observed, workerStatus: "running" }],
        "database",
        "Items.json",
      )?.id,
      observed.id,
    );
  }
  // A stale submitted flag must not turn ended, missing or unrelated Batches
  // into current work, even during automatic monitoring or collection.
  const provider = checkpoint.process!.batches![0];
  for (const status of [
    "completed",
    "ended",
    "failed",
    "expired",
    "cancelled",
    "canceled",
    "unknown",
  ]) {
    for (const monitor of [
      undefined,
      { state: "monitoring" as const, message: "" },
      { state: "collecting" as const, message: "" },
    ]) {
      const ended = {
        ...checkpoint,
        status: "stopped",
        process: {
          ...checkpoint.process!,
          batches: [{ ...provider, status }],
          monitoring: monitor,
        },
      };
      assert.equal(
        fileStatus("Items.json", ended).label,
        "Needs review",
        status,
      );
      assert.equal(
        fileStatus("Items.json", {
          ...ended,
          outputs: {},
          availableOutputs: [],
        }).label,
        "Needs review",
        status,
      );
      assert.equal(needsSubmissionReview(ended), true);
    }
  }
  for (const batches of [
    [],
    [{ ...provider, requestIndices: undefined }],
    [{ ...provider, requestIndices: [1] }],
  ]) {
    assert.equal(
      fileStatus("Items.json", {
        ...checkpoint,
        process: { ...checkpoint.process!, batches },
      }).label,
      "Needs review",
    );
  }
  for (const status of [
    "validating",
    "in_progress",
    "finalizing",
    "cancelling",
    "canceling",
  ]) {
    const current = {
      ...stopped,
      process: { ...stopped.process!, batches: [{ ...provider, status }] },
    };
    assert.equal(fileStatus("Items.json", current).label, "Working");
  }
  const clarification = {
    ...provider,
    id: "retry",
    clarification: true,
    originalBatchId: provider.id,
  };
  const original = { ...provider, status: "completed" };
  assert.equal(
    fileStatus("Items.json", {
      ...stopped,
      process: { ...stopped.process!, batches: [original, clarification] },
    }).label,
    "Working",
  );
  assert.equal(
    fileStatus("Items.json", {
      ...stopped,
      process: {
        ...stopped.process!,
        batches: [original, { ...clarification, status: "cancelled" }],
      },
    }).label,
    "Needs review",
  );
  // A grouped retry with its own index cannot borrow its parent's active receipt.
  const retried = {
    ...stopped,
    process: {
      ...stopped.process!,
      requests: [
        { index: 0, file: "Items.json", state: "rejected", sourceItems: 1 },
        {
          index: 1,
          file: "Items.json",
          state: "submitted",
          sourceItems: 1,
          clarificationOf: 0,
        },
      ],
    },
  };
  assert.equal(fileStatus("Items.json", retried).label, "Needs review");
  assert.equal(
    fileStatus("Items.json", {
      ...retried,
      process: {
        ...retried.process,
        batches: [original, { ...clarification, requestIndices: [1] }],
      },
    }).label,
    "Working",
  );
  const finished = {
    ...monitoring,
    process: {
      ...monitoring.process,
      batches: [original],
      requests: monitoring.process.requests!.map((row) => ({
        ...row,
        providerFinished: true,
      })),
    },
  };
  assert.equal(fileStatus("Items.json", finished).label, "Working");
  assert.equal(
    fileStatus("Items.json", {
      ...finished,
      process: { ...finished.process, monitoring: undefined },
    }).label,
    "Working",
  );
  assert.equal(
    fileStatus("Items.json", {
      ...finished,
      process: { ...finished.process, batches: [] },
    }).label,
    "Needs review",
  );
});

// Live inspection must follow new receipts while a stale full-detail read and
// old log are retained; another project/run must never replace the selection.
test("Live inspection and file progress follow current receipts without Batch controls", () => {
  const live = {
    id: "live",
    mode: "translate",
    status: "running",
    files: ["Items.json"],
    updated: "2026-10-04T10:00:00Z",
    log: ["retained"],
    progress: { file: "Items.json", current: 0, total: 1 },
    itemProgress: { file: "Items.json", current: 12, total: 50 },
    process: {
      requests: [
        { index: 0, file: "Items.json", state: "submitted", sourceItems: 50 },
      ],
      errors: [],
    },
  } as Job;
  assert.equal(fileStatus("Items.json", live).label, "Working");
  assert.equal(
    fileStatus("Items.json", {
      ...live,
      process: {
        ...live.process!,
        requests: [
          { index: 0, file: "Items.json", state: "validated", sourceItems: 50 },
        ],
      },
    }).label,
    "Working",
  );
  const rejected = {
    index: 1,
    file: "Items.json",
    state: "rejected",
    sourceItems: 50,
  };
  assert.equal(
    fileStatus("Items.json", {
      ...live,
      process: {
        ...live.process!,
        requests: [...live.process!.requests!, rejected],
      },
    }).label,
    "Working",
  );
  // Before the first file finishes, only itemProgress identifies active parsing.
  // All receipts can be rejected while the worker continues to its next request.
  const betweenRequests = {
    ...live,
    progress: undefined,
    process: {
      errors: [],
      requests: [rejected],
      validationIssues: [{ file: "Items.json", rejected: 1 }],
    },
  };
  assert.equal(fileStatus("Items.json", betweenRequests).pending, true);
  assert.equal(
    fileStatus("Items.json", {
      ...betweenRequests,
      availableOutputs: ["Items.json"],
      partialOutputs: ["Items.json"],
    }).label,
    "Working",
  );
  for (const status of ["stopped", "failed", "complete"]) {
    assert.equal(
      fileStatus("Items.json", { ...betweenRequests, status }).pending,
      false,
    );
    assert.equal(
      fileStatus("Items.json", { ...betweenRequests, status }).label,
      "Needs review",
    );
  }
  // Moving to another file must not revive the last completed file's activity.
  const nextFile = {
    ...betweenRequests,
    files: ["Items.json", "Armors.json"],
    progress: { file: "Items.json", current: 1, total: 2 },
    itemProgress: { file: "Armors.json", current: 0, total: 20 },
  };
  assert.equal(fileStatus("Items.json", nextFile).label, "Needs review");
  assert.equal(fileStatus("Armors.json", nextFile).label, "Working");
  assert.equal(
    fileStatus("Items.json", {
      ...nextFile,
      availableOutputs: ["Items.json"],
      process: { errors: [] },
    }).label,
    "Ready to apply",
  );
  assert.equal(translationStopLabel(live), "Stop translation");
  assert.equal(
    fileStatus("Items.json", {
      ...live,
      status: "stopped",
      availableOutputs: ["Items.json"],
      partialOutputs: ["Items.json"],
    }).label,
    "Needs review",
  );
  assert.equal(
    fileStatus("Items.json", { ...live, status: "failed" }).label,
    "Needs review",
  );
  assert.equal(
    fileStatus("Items.json", {
      ...live,
      status: "complete",
      availableOutputs: ["Items.json"],
    }).label,
    "Ready to apply",
  );
  // A stopped/failed worker and an earlier rejected attempt must not hide the
  // file's saved progress or make the outcome depend on Live versus Batch.
  for (const mode of ["translate", "batch"])
    for (const status of ["failed", "stopped", "interrupted", "complete"]) {
      const partial = {
        ...live,
        mode,
        status,
        availableOutputs: ["Items.json"],
        partialOutputs: ["Items.json"],
        process: { errors: [], requests: [rejected] },
      };
      assert.equal(fileStatus("Items.json", partial).label, "Needs review");
      assert.equal(fileStatus("Items.json", partial).state, "needs_review");
      assert.equal(
        fileStatus("Items.json", { ...partial, availableOutputs: [] }).label,
        "Needs review",
      );
    }
  const clarified = {
    ...live,
    process: {
      errors: [],
      requests: [
        rejected,
        { ...rejected, index: 2, state: "submitted", clarificationOf: 1 },
      ],
    },
  };
  assert.equal(fileStatus("Items.json", clarified).state, "working");
  const completed = {
    ...live,
    updated: "2026-10-04T10:00:01Z",
    status: "complete",
    log: [],
  };
  assert.equal(observedRun(live, completed)?.status, "complete");
  assert.deepEqual(observedRun(live, completed)?.log, ["retained"]);
  assert.equal(observedRun(completed, live), completed);
  assert.equal(observedRun(live, { ...completed, id: "foreign" }), live);
});

test("file line amounts count each source request once at its latest attempt", () => {
  // A retried request must not count its lines twice, and duplicate
  // responses never add lines.
  const run = {
    id: "run",
    status: "complete",
    mode: "translate",
    logicalPhase: "database",
    files: ["Items.json"],
    created: "2026-10-05T10:00:00+00:00",
    log: [],
    message: "",
    process: {
      errors: [],
      requests: [
        { index: 0, state: "validated", file: "Items.json", sourceItems: 40 },
        { index: 1, state: "rejected", file: "Items.json", sourceItems: 10 },
        { index: 2, state: "validated", file: "Other.json", sourceItems: 5 },
        { index: 3, state: "unused", file: "Items.json", sourceItems: 7 },
      ],
    },
  } as Job;
  const state = (runs: Job[], noRequests = {}) =>
    ({
      runs,
      sourceStatus: { changed: [], ready: [], noRequests },
    }) as unknown as GuidedState;
  const lines = (value: GuidedState) =>
    fileLines(value, "database", "Items.json");
  assert.deepEqual(lines(state([run])), { done: 40, total: 50 });
  const retried = {
    ...run,
    process: {
      ...run.process!,
      requests: [
        ...run.process!.requests!,
        {
          index: 4,
          state: "validated",
          file: "Items.json",
          sourceItems: 10,
          clarificationOf: 1,
        },
      ],
    },
  } as Job;
  assert.deepEqual(lines(state([retried])), { done: 50, total: 50 });
  // A later "nothing to translate" check closes the file at what is done.
  assert.deepEqual(
    lines(
      state([run], { database: { "Items.json": "2026-10-05T12:00:00+00:00" } }),
    ),
    { done: 40, total: 40 },
  );
  assert.deepEqual(lines(state([])), { done: 0, total: null });
  // A running Live run prepares requests as it goes; its total is unknown
  // until it ends, so no denominator grows under the reader.
  assert.deepEqual(lines(state([{ ...run, status: "running" }])), {
    done: 40,
    total: null,
    running: true,
  });
  // One that stopped early never prepared the rest, so the lines it did
  // prepare are not the file's total.
  assert.deepEqual(lines(state([{ ...run, status: "stopped" }])), {
    done: 40,
    total: null,
  });
});

test("text locations name the editor's event, page and command, counting from one", () => {
  assert.equal(
    textLocation("/events/1/pages/0/list/20/parameters/0"),
    "Event 1 · page 1 · command 21",
  );
  assert.equal(
    textLocation("/7/pages/2/list/0/parameters/0"),
    "Troop 7 · page 3 · command 1",
  );
  assert.equal(
    textLocation("/106/list/4/parameters/1"),
    "Common event 106 · command 5",
  );
  assert.equal(textLocation("/3/description"), "Entry 3 · description");
  assert.equal(textLocation("/terms/messages/x"), "terms › messages › x");
});
