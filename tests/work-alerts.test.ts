import assert from "node:assert/strict";
import test from "node:test";
import type {
  AssistantTaskRecord,
  Job,
  TranslationJob,
  WorkspaceSnapshot,
} from "../app/src/api/contracts.ts";
import { WorkAlerts } from "../app/src/app/workAlerts.ts";

const project = (method: "guided" | "len") => ({
  id: "game",
  name: "ホロウワルド",
  source: "/games/hollow",
  engine: "MVMZ",
  method,
  phase: "",
  available: true,
});

function guided(runs: Partial<Job>[], operations: Partial<Job>[] = []) {
  return {
    application: { project: project("guided") },
    assistantTasks: [],
    translation: { projectId: "game", jobs: [], lifecycle: {} },
    guided: {
      projectId: "game",
      runs,
      operations,
      estimates: {},
      phaseRuns: {},
      readiness: { qa: { current: false, applied: false, questions: [] } },
    },
  } as unknown as WorkspaceSnapshot;
}

test("Guided work the user may have left alerts once it ends or waits, unless it was short", () => {
  const alerts = new WorkAlerts();
  const run = (status: string, extra: Partial<Job> = {}) => ({
    id: "maps",
    status,
    mode: "translate",
    logicalPhase: "dialogue" as const,
    log: [],
    message: "",
    ...extra,
  });
  // Opening a game only notes where its work stands.
  assert.equal(alerts.observe(guided([run("complete")]), 0), null);
  assert.equal(alerts.observe(guided([run("running")]), 1_000), null);
  assert.equal(alerts.observe(guided([run("running")]), 6_000), null);
  assert.deepEqual(
    alerts.observe(
      guided([run("complete", { availableOutputs: ["Map001.json"] })]),
      20_000,
    ),
    { title: "ホロウワルド", lines: ["Maps & events · Live · Output saved"] },
  );
  // A step that ends within seconds ended in front of the user.
  const setup = (status: string) => ({
    id: "setup",
    label: "Set up",
    status,
    log: [],
    message: "",
  });
  alerts.observe(guided([], [setup("running")]), 30_000);
  assert.equal(alerts.observe(guided([], [setup("complete")]), 33_000), null);
  // A Batch that prepared for a while waits for its cost review.
  const batch = (status: string) => ({
    ...run(status),
    id: "batch",
    mode: "batch",
    logicalPhase: "database" as const,
    approval: status === "waiting" ? { token: "t", kind: "batch" } : null,
  });
  alerts.observe(guided([batch("running")]), 40_000);
  assert.deepEqual(alerts.observe(guided([batch("waiting")]), 60_000)?.lines, [
    "Database · Batch · Review cost",
  ]);
  // Approving it in the window starts its clock again.
  alerts.observe(guided([batch("running")]), 61_000);
  assert.equal(alerts.observe(guided([batch("failed")]), 63_000), null);
});

test("Assistant-led alerts come from the assistant, never its helper steps", () => {
  const record = (
    resultAt: string | null,
    dismissed = false,
  ): AssistantTaskRecord => ({
    kind: "walkthrough",
    requestId: "",
    copiedAt: "2026-10-12T10:00:00.000Z",
    resultAt,
    dismissed,
  });
  const len = (
    jobs: Partial<TranslationJob>[],
    blocker = "",
    records = [record(null)],
  ) =>
    ({
      application: { project: project("len") },
      assistantTasks: records,
      guided: null,
      translation: {
        projectId: "game",
        jobs,
        lifecycle: {},
        progress: {
          updated_at: "2026-10-12T10:00:00.000Z",
          phases: { translation: "active" },
          blocker,
          next_action: "",
        },
      },
    }) as unknown as WorkspaceSnapshot;
  const step = (status: string) => ({
    id: "extract",
    kind: "operation" as const,
    action: "extract",
    label: "Extract text",
    status,
  });
  const alerts = new WorkAlerts();
  alerts.observe(len([step("running")]), 0);
  assert.equal(alerts.observe(len([step("complete")]), 60_000), null);
  assert.deepEqual(
    alerts.observe(len([], "Which honorifics should stay?"), 61_000)?.lines,
    ["Your assistant needs you: Which honorifics should stay?"],
  );
  const quote = {
    id: "api",
    kind: "translation" as const,
    mode: "live" as const,
    label: "API run",
    status: "ready",
    approved: false,
    quote: { cost: 1 } as TranslationJob["quote"],
    created: "2026-10-12T11:00:00.000Z",
  };
  assert.deepEqual(alerts.observe(len([quote]), 62_000)?.lines, [
    "An API estimate waits for your approval",
  ]);
  assert.deepEqual(
    alerts.observe(
      len([quote], "", [record("2026-10-12T10:30:00.000Z")]),
      63_000,
    )?.lines,
    ["Your assistant finished Player walkthrough"],
  );
  // Dismissing a task in the window is not the assistant handing it back.
  alerts.observe(len([quote], "", [record(null)]), 64_000);
  assert.equal(
    alerts.observe(len([quote], "", [record(null, true)]), 65_000),
    null,
  );
});
