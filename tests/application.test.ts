import assert from "node:assert/strict";
import test from "node:test";
import {
  ApplicationStore,
  type ApplicationSource,
} from "../app/src/app/applicationStore.ts";
import type { WorkspaceSnapshot } from "../app/src/api/contracts.ts";

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
function setup(read: ApplicationSource["snapshot"]) {
  let mutation: (phase: "begin" | "end") => void = () => {};
  let stopped: (message: string) => void = () => {};
  const store = new ApplicationStore({
    snapshot: read,
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
