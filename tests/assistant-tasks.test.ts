import assert from "node:assert/strict";
import test from "node:test";
import type {
  AssistantTaskRecord,
  GuidedState,
  ImageManagerState,
  PluginState,
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
  // An MV/MZ page is validated after it is published, so only a passing
  // report saved after its last save finishes the task.
  const validated = (savedAt: string, passed: boolean) => ({
    records: [
      { ...later.records[0], validation: { savedAt, passed, errors: 0 } },
    ],
  });
  for (const [sources, state] of [
    [{ records: [{ ...later.records[0], validation: null }] }, "waiting"],
    [validated("2026-10-07T10:31:00.000+00:00", false), "waiting"],
    [validated("2026-10-07T10:29:00.000+00:00", true), "waiting"],
    [validated("2026-10-07T10:31:00.000+00:00", true), undefined],
  ] as const)
    assert.equal(assistantTasks(sources)[0]?.state, state);

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

  // Preparing QA from the page copies the new task; a copy of an earlier one
  // waits only on a task its assistant prepared since, such as QA's next
  // round after an apply.
  const qa = (
    requestId: string,
    task: Partial<GuidedState["readiness"]["qa"]> = {},
    finishedAt?: string | null,
  ) => ({
    records: [
      {
        kind: "qa",
        requestId,
        copiedAt: "2026-10-07T10:00:00.000+00:00",
        resultAt: null,
        dismissed: false,
        ...(finishedAt !== undefined && { finishedAt }),
      } as AssistantTaskRecord,
    ],
    guided: {
      engine: "MVMZ",
      speakerSetup: {},
      speakerScan: {},
      contextSetup: { documents: {} },
      eventText: { status: "missing" },
      operations: [],
      readiness: {
        qa: {
          task: "/qa/release/new",
          current: true,
          findings: [],
          questions: [],
          status: { stage: "screen" },
          prepared_at: "2026-10-07T09:00:00.000000+00:00",
          ...task,
        },
        playtest: { current: false, problems: [], gaps: [] },
        publications: [],
      },
    } as unknown as GuidedState,
  });
  const states = (sources: ReturnType<typeof qa>) =>
    assistantTasks(sources).map((task) => [task.state, task.detail]);
  assert.deepEqual(states(qa("old")), []);
  assert.deepEqual(states(qa("new")), [["waiting", ""]]);
  const nextRound = { prepared_at: "2026-10-07T11:00:00.000000+00:00" };
  assert.deepEqual(states(qa("old", nextRound)), [["waiting", ""]]);
  const stale = { current: false, message: "Changed." };
  assert.deepEqual(states(qa("new", stale)), [["outdated", "Changed."]]);
  // A copy for MV/MZ names the playtest's report: after QA's apply its
  // assistant plays the game again, so the task waits until a playtest of the
  // game as it is settles, fixing a crash that stops the game first. A game
  // the playtest can't play for want of its engine's scripts settles it too.
  // A copy made before the playtest joined the task finishes with QA.
  const applied = { applied: true, status: { stage: "complete" } };
  const copy = qa("new", applied, null);
  assert.deepEqual(states(copy), [["waiting", ""]]);
  assert.deepEqual(states(qa("new", applied)), []);
  const crash = {
    kind: "crash",
    check: "runtime-crash",
    file: "js/plugins/Menu.js",
    note: "The game stopped at its error screen.",
    fix: "game",
  } as const;
  copy.guided.readiness.playtest = {
    report: "r",
    current: true,
    played: false,
    problems: [crash],
    gaps: ["Title screen: The game stopped."],
  };
  assert.deepEqual(states(copy), [["waiting", ""]]);
  copy.guided.readiness.playtest.problems = [];
  copy.guided.readiness.playtest.gaps = [
    "The game folder has no RPG Maker engine scripts to play.",
  ];
  assert.deepEqual(states(copy), []);
  // A play running, such as a check of the assistant's fixes, is still work.
  copy.guided.readiness.playtest.played = true;
  copy.guided.operations = [
    { id: "p", action: "playtest_fix", status: "running", log: [] },
  ];
  assert.deepEqual(states(copy), [["waiting", ""]]);
  copy.guided.operations = [];
  assert.deepEqual(states(copy), []);

  // A finished plugin task reads Outdated once a plugin changes, and Blocked
  // while a file cannot be read; its panel shares this state.
  const plugins = (
    counts: Partial<PluginState["counts"]>,
    unreadable: string[] = [],
    kept = false,
  ) => ({
    records: [
      {
        kind: "plugins",
        requestId: "request",
        copiedAt: "2026-10-07T10:00:00.000+00:00",
        resultAt: null,
        dismissed: false,
      } as AssistantTaskRecord,
    ],
    plugins: {
      scanned: true,
      awaiting: false,
      unreadable: unreadable.map((path) => ({
        path,
        issue: "Not UTF-8.",
        kept,
      })),
      counts: {
        files: 1,
        investigated: 1,
        textFiles: 0,
        selected: 0,
        translated: 0,
        ready: 0,
        applied: 0,
        ...counts,
      },
    } as unknown as PluginState,
  });
  assert.deepEqual(
    assistantTasks(plugins({ files: 2 })).map((task) => [
      task.state,
      task.detail,
    ]),
    [["outdated", "1 plugin file changed since your assistant finished"]],
  );
  assert.deepEqual(
    assistantTasks(plugins({}, ["js/plugins/Old.js"])).map(
      (task) => task.state,
    ),
    ["blocked"],
  );
  assert.deepEqual(assistantTasks(plugins({})), []);
  // Keeping the file unchanged lets the task finish.
  assert.deepEqual(
    assistantTasks(plugins({}, ["js/plugins/Old.js"], true)),
    [],
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

  // Names & glossary saves its first results long before its assistant
  // stops; it waits until the widths it saves last arrive.
  const names = (finishedAt?: string | null) => ({
    records: [
      {
        kind: "names",
        requestId: "request",
        copiedAt: "2026-10-07T10:00:00.000+00:00",
        resultAt: "2026-10-07T10:05:00.000+00:00",
        dismissed: false,
        ...(finishedAt !== undefined && { finishedAt }),
      } as AssistantTaskRecord,
    ],
    guided: {
      speakerSetup: { status: "applied", reportId: "report", rules: [] },
      speakerScan: { available: true, names: [], files: 1 },
      contextSetup: {
        status: "ready",
        documents: Object.fromEntries(
          ["glossary", "quirks", "game"].map((name) => [
            name,
            { exists: true },
          ]),
        ),
      },
      eventText: { status: "missing" },
    } as unknown as GuidedState,
  });
  for (const finishedAt of [null, "2026-10-06T09:00:00.000+00:00"])
    assert.equal(assistantWaiting("names", names(finishedAt)).waiting, true);
  assert.deepEqual(assistantTasks(names("2026-10-07T10:40:00.000+00:00")), []);
  // A copy recorded before tasks named their last result finishes as before.
  assert.deepEqual(assistantTasks(names()), []);

  // A line width report saved after the copy finishes the task, measured or
  // not; until it comes back the task waits.
  const widths = (contextSetup: object, resultAt: string | null) => ({
    records: [
      {
        kind: "line_widths",
        requestId: "request",
        copiedAt: "2026-10-07T10:00:00.000+00:00",
        resultAt,
        dismissed: false,
      } as AssistantTaskRecord,
    ],
    guided: {
      ...names().guided,
      contextSetup: { documents: {}, layout: null, ...contextSetup },
    } as unknown as GuidedState,
  });
  const back = "2026-10-07T10:20:00.000+00:00";
  assert.deepEqual(
    assistantTasks(widths({ layoutUnmeasured: true }, back)),
    [],
  );
  assert.deepEqual(
    assistantTasks(widths({ layoutUnmeasured: true }, null)).map(
      (task) => task.state,
    ),
    ["waiting"],
  );
  assert.deepEqual(
    assistantTasks(widths({}, back)).map((task) => task.state),
    ["waiting"],
  );
  // A report the app cannot use is blocked with its reason, even one another
  // task saved; a new copy waits for its own report.
  const reason = { layoutRejected: "Layout evidence needs a hash." };
  for (const sources of [
    widths(reason, back),
    { ...widths(reason, back), records: [] },
  ])
    assert.deepEqual(
      assistantTasks(sources).map((task) => [task.state, task.detail]),
      [["blocked", reason.layoutRejected]],
    );
  assert.deepEqual(
    assistantTasks(widths(reason, null)).map((task) => task.state),
    ["waiting"],
  );
});

test("Recovery lists each plugin application once through undos and redos", async () => {
  const { recoveryRows } =
    await import("../app/src/features/plugins/pluginTask.ts");
  const receipt = (id: string, mode: string, names = {}) =>
    ({ id, mode, saved: id, status: "complete", ...names }) as never;
  // Undone in Recovery, brought back and undone again from Checkpoints;
  // each added a row of its own beside an earlier reviewed restore.
  const rows = recoveryRows([
    receipt("restore", "restore"),
    receipt("apply", "apply"),
    receipt("undo", "restore", { restores: "apply" }),
    receipt("redo", "apply", { applies: "apply" }),
    receipt("undo-again", "restore", { restores: "redo" }),
  ]);
  assert.deepEqual(
    rows.map((row) => [row.application.id, row.latest.id]),
    [
      ["apply", "undo-again"],
      ["restore", "restore"],
    ],
  );
});
