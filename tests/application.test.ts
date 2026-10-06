import assert from "node:assert/strict";
import test from "node:test";
import {
  ApplicationStore,
  type ApplicationSource,
} from "../app/src/app/applicationStore.ts";
import type {
  GuidedState,
  Project,
  WorkspaceSnapshot,
} from "../app/src/api/contracts.ts";
import {
  fileRun,
  fileStatus,
} from "../app/src/features/guided/translationView.ts";
import { reconcile, replied } from "../app/src/state/useObserved.ts";

const turn = () => new Promise<void>((resolve) => setImmediate(resolve));
const snapshot = (ready = false): WorkspaceSnapshot => ({
  application: {
    project: null,
    recent: [],
    screen: "overview",
    running: false,
    observing: false,
    provider_ready: ready,
  },
  guided: null,
  translation: null,
  translationError: "",
});
function setup(
  read: ApplicationSource["snapshot"],
  navigationStorage?: ApplicationSource["navigationStorage"],
) {
  let mutation: (phase: "begin" | "end") => void = () => {};
  let stopped: (message: string) => void = () => {};
  const store = new ApplicationStore({
    snapshot: read,
    navigationStorage,
    onMutation: (handler) => {
      mutation = handler;
      return () => {
        mutation = () => {};
      };
    },
    onStopped: (handler) => {
      stopped = handler;
      return () => {
        stopped = () => {};
      };
    },
  });
  return {
    store,
    mutate: (phase: "begin" | "end") => mutation(phase),
    disconnect: (message: string) => stopped(message),
  };
}

test("concurrent refreshes share a read and discard snapshots preceding a mutation", async (t) => {
  const pending = Promise.withResolvers<WorkspaceSnapshot>();
  const current = snapshot(true);
  let calls = 0;
  const { store, mutate } = setup(() =>
    ++calls === 1 ? pending.promise : Promise.resolve(current),
  );
  t.after(() => store.stop());
  store.start();
  const reading = store.refresh();
  assert.equal(store.refresh(), reading);
  assert.equal(calls, 1);
  mutate("begin");
  pending.resolve(snapshot());
  await turn();
  assert.equal(store.getSnapshot().snapshot, null);
  assert.equal(calls, 1);
  mutate("end");
  await reading;
  assert.equal(store.getSnapshot().snapshot, current);
});

test("chained writes do not start an intermediate snapshot before the next operation", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  let next: Promise<WorkspaceSnapshot> | undefined;
  const { store, mutate } = setup(async () => {
    calls++;
    return next || snapshot();
  });
  t.after(() => store.stop());
  store.start();
  await store.refresh();
  await store.settle();
  assert.equal(calls, 1); // A local/read-only action has nothing to refresh.
  mutate("begin");
  mutate("end");
  // A draft save resolves into the action's awaiting navigation continuation.
  await Promise.resolve();
  mutate("begin");
  t.mock.timers.tick(0);
  assert.equal(calls, 1);
  mutate("end");
  // Explicit completion need not wait for the automatic refresh timer.
  await store.settle();
  assert.equal(calls, 2);
  t.mock.timers.tick(0);
  assert.equal(calls, 2);
  mutate("begin");
  mutate("end");
  t.mock.timers.tick(0);
  await store.refresh();
  assert.equal(calls, 3);
  const pending = Promise.withResolvers<WorkspaceSnapshot>();
  next = pending.promise;
  const reading = store.refresh();
  mutate("begin");
  mutate("end");
  next = undefined;
  pending.resolve(snapshot());
  await reading;
  assert.equal(calls, 5);
  t.mock.timers.tick(0);
  assert.equal(calls, 5); // The in-flight read already supplied the refresh.
});

const projectSnapshot = (id: string): WorkspaceSnapshot => ({
  ...snapshot(),
  application: { ...snapshot().application, project: { id } as Project },
  guided: {
    projectId: id,
    step: "context",
    task: "guidance",
    positions: { context: "guidance" },
    contextDocument: "glossary",
    documents: {
      glossary: { text: "", revision: "one" },
      game: { text: "", revision: "two" },
    },
    drafts: {},
    eventText: { view: "audit" },
    form: { text: { view: "apply" } },
  } as GuidedState,
});

test("navigation completes during an outstanding observation without losing newer project evidence", async (t) => {
  const initial = projectSnapshot("one");
  initial.guided!.runs = [
    {
      id: "new",
      status: "complete",
      workerStatus: "complete",
      mode: "batch",
      logicalPhase: "dialogue",
      files: ["Map001.json"],
      availableOutputs: ["Map001.json"],
      message: "",
      log: [],
    },
    {
      id: "old",
      status: "stopped",
      workerStatus: "stopped",
      mode: "batch",
      logicalPhase: "dialogue",
      files: ["Map001.json"],
      message: "",
      log: [],
    },
  ];
  const status = () =>
    fileStatus(
      "Map001.json",
      fileRun(
        store.getSnapshot().snapshot!.guided!.runs,
        "dialogue",
        "Map001.json",
      ),
    );
  const pending = Promise.withResolvers<WorkspaceSnapshot>();
  let calls = 0;
  const { store } = setup(() =>
    ++calls === 1 ? Promise.resolve(initial) : pending.promise,
  );
  t.after(() => store.stop());
  store.start();
  await store.refresh();
  const before = status();
  const reading = store.refresh();
  store.navigate("guided");
  store.navigateGuided("one", {
    step: "translate",
    task: "dialogue",
    eventView: "sources",
    textView: "fitting",
    contextDocument: "game",
  });
  let settled = false;
  void store.settle().then(() => {
    settled = true;
  });
  await turn();
  assert.equal(settled, true);
  assert.equal(calls, 2);
  assert.equal(store.getSnapshot().snapshot?.guided?.task, "dialogue");
  assert.deepEqual(status(), before);
  pending.resolve({
    ...initial,
    application: { ...initial.application, provider_ready: true },
    guided: {
      ...initial.guided!,
      runs: [
        initial.guided!.runs[0],
        {
          ...initial.guided!.runs[1],
          status: "running",
          process: {
            errors: [],
            monitoring: { state: "monitoring", message: "Checking provider" },
          },
        },
      ],
    },
  });
  await reading;
  const value = store.getSnapshot().snapshot!;
  assert.equal(value.application.screen, "guided");
  assert.equal(value.application.provider_ready, true);
  assert.equal(value.guided?.task, "dialogue");
  assert.equal(value.guided?.contextDocument, "game");
  assert.equal(value.guided?.eventText.view, "sources");
  assert.equal(value.guided?.form.text.view, "fitting");
  assert.deepEqual(status(), before);
});

test("workflow views persist per project and storage failures leave the previous view usable", async (t) => {
  const records = new Map<string, string>();
  let fail = false;
  const storage = {
    getItem: (key: string) => records.get(key) || null,
    setItem: (key: string, value: string) => {
      if (fail) throw new Error("Storage unavailable");
      records.set(key, value);
    },
  };
  let current = projectSnapshot("one");
  const { store } = setup(async () => current, storage);
  t.after(() => store.stop());
  store.start();
  await store.refresh();
  store.navigate("guided");
  store.navigateGuided("one", { step: "translate", task: "dialogue" });
  fail = true;
  assert.throws(
    () => store.navigateGuided("one", { step: "apply", task: "apply" }),
    /Storage unavailable/,
  );
  assert.equal(store.getSnapshot().snapshot?.guided?.task, "dialogue");
  fail = false;
  current = projectSnapshot("two");
  await store.refresh();
  assert.equal(store.getSnapshot().snapshot?.application.screen, "overview");
  assert.equal(store.getSnapshot().snapshot?.guided?.task, "guidance");
  assert.throws(
    () => store.navigateGuided("one", { task: "apply" }),
    /workspace first/,
  );
  store.stop();
  const restored = setup(async () => projectSnapshot("one"), storage).store;
  t.after(() => restored.stop());
  restored.start();
  await restored.refresh();
  assert.equal(restored.getSnapshot().snapshot?.guided?.task, "dialogue");
  assert.deepEqual(restored.getSnapshot().snapshot?.guided?.positions, {
    context: "guidance",
    translate: "dialogue",
  });
  assert.ok([...records.values()].every((raw) => !raw.includes('"documents"')));
});

test("a late successful read cannot hide a backend disconnection", async (t) => {
  const pending = Promise.withResolvers<WorkspaceSnapshot>();
  const { store, disconnect } = setup(() => pending.promise);
  t.after(() => store.stop());
  store.start();
  const reading = store.refresh();
  disconnect("Backend stopped");
  pending.resolve(snapshot());
  await reading;
  assert.equal(store.getSnapshot().stopped, true);
  assert.equal(store.getSnapshot().error, "Backend stopped");
  assert.equal(store.getSnapshot().snapshot, null);
});

test("a stopped observer cannot publish an outstanding snapshot", async () => {
  const pending = Promise.withResolvers<WorkspaceSnapshot>();
  const { store } = setup(() => pending.promise);
  store.start();
  const reading = store.refresh();
  store.stop();
  pending.resolve(snapshot());
  await reading;
  assert.equal(store.getSnapshot().snapshot, null);
});

test("external project reports refresh even while no app job is running", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  const value = snapshot();
  value.application.observing = true;
  const { store } = setup(async () => {
    calls++;
    return value;
  });
  t.after(() => store.stop());
  store.start();
  await store.refresh();
  assert.equal(calls, 1);
  t.mock.timers.tick(2000);
  await store.refresh();
  assert.equal(calls, 2);
  store.stop();
  t.mock.timers.tick(10000);
  assert.equal(calls, 2);
});

test("held views refresh progress, adopt snapshots after release, and keep newer replies", () => {
  type State = { revision: number; progress: number };
  const merge = (current: State, next: State) => ({
    ...current,
    progress: next.progress,
  });
  const before = { revision: 1, progress: 0 };
  const reply = replied<State, State>({ revision: 2, progress: 0 }, before);
  const progress = { revision: 2, progress: 5 };
  const held = reconcile(reply, progress, true, merge);
  assert.deepEqual(held.value, { revision: 2, progress: 5 });
  assert.equal(reconcile(held, progress, true, merge), held);
  const released = reconcile(held, progress, false, merge);
  assert.equal(released.value, progress);
  assert.deepEqual(released.adopted?.previous, held.value);
  const newer = replied<State, State>({ revision: 3, progress: 5 }, progress);
  assert.equal(reconcile(newer, progress, false, merge), newer);
});
