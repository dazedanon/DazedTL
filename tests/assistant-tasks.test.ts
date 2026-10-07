import assert from "node:assert/strict";
import test from "node:test";
import type {
  AssistantTaskRecord,
  GuidedState,
  ImageManagerState,
} from "../app/src/api/contracts.ts";
import {
  assistantTasks,
  assistantWaiting,
  withHandoff,
} from "../app/src/features/assistant/assistantTasks.ts";

test("copied tasks wait for a newer result, and dismissed ones read Not started", () => {
  const walkthrough = (resultAt: string | null, dismissed = false) => ({
    records: [
      {
        kind: "walkthrough",
        requestId: "",
        copiedAt: "2026-10-07T10:00:00.000+00:00",
        resultAt,
        dismissed,
      } as AssistantTaskRecord,
    ],
  });
  // A walkthrough page from an earlier copy does not finish the new one.
  const earlier = walkthrough("2026-10-06T09:00:00.000+00:00");
  assert.deepEqual(
    assistantTasks(earlier).map((task) => [task.kind, task.state, task.since]),
    [["walkthrough", "waiting", "2026-10-07T10:00:00.000+00:00"]],
  );
  const later = walkthrough("2026-10-07T10:30:00.000+00:00");
  assert.deepEqual(assistantTasks(later), []);
  assert.equal(assistantWaiting("walkthrough", later).saved, true);
  assert.equal(assistantWaiting("walkthrough", earlier).saved, false);
  // Dismissing leaves the list and its feature's own panel stops waiting.
  const dismissed = walkthrough(null, true);
  assert.deepEqual(assistantTasks(dismissed), []);
  const handoff = assistantWaiting("walkthrough", dismissed);
  assert.equal(withHandoff("waiting", handoff), "not_started");
  assert.equal(
    withHandoff("not_started", assistantWaiting("walkthrough", earlier)),
    "waiting",
  );

  // Copying an unchanged image task again reuses its request, so its report
  // still reads complete; it waits until a newer report is saved.
  const recopied = {
    records: [
      {
        kind: "image_discovery",
        requestId: "same",
        copiedAt: "2026-10-07T10:00:00.000+00:00",
        resultAt: "2026-10-07T09:00:00.000+00:00",
        dismissed: false,
      } as AssistantTaskRecord,
    ],
    images: {
      discovery: { status: "complete" },
      editing: { status: "idle" },
      counts: { needsReview: 0 },
    } as unknown as ImageManagerState,
  };
  assert.deepEqual(
    assistantTasks(recopied).map((task) => task.state),
    ["waiting"],
  );

  // Preparing QA again makes a new task; a copy of the earlier one does not
  // wait on it.
  const qa = (requestId: string) => ({
    records: [
      {
        kind: "qa",
        requestId,
        copiedAt: "2026-10-07T10:00:00.000+00:00",
        resultAt: null,
        dismissed: false,
      } as AssistantTaskRecord,
    ],
    guided: {
      speakerSetup: {},
      speakerScan: {},
      contextSetup: { documents: {} },
      eventText: { status: "missing" },
      readiness: {
        qa: {
          task: "/qa/release/new",
          current: true,
          findings: [],
          status: { stage: "screen" },
        },
        publications: [],
      },
    } as unknown as GuidedState,
  });
  assert.deepEqual(assistantTasks(qa("old")), []);
  assert.deepEqual(
    assistantTasks(qa("new")).map((task) => task.state),
    ["waiting"],
  );

  // An image task copied before records existed still lists while it waits.
  const images = {
    discovery: { status: "awaiting_results", copiedAt: "2026-10-05T08:00:00Z" },
    editing: { status: "idle" },
    counts: { needsReview: 0 },
  } as unknown as ImageManagerState;
  assert.deepEqual(
    assistantTasks({ records: [], images }).map((task) => [
      task.kind,
      task.state,
      task.since,
    ]),
    [["image_discovery", "waiting", "2026-10-05T08:00:00Z"]],
  );
});
