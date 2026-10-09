import assert from "node:assert/strict";
import test from "node:test";
import { DraftSession } from "../app/src/state/DraftSession.ts";
import {
  flushDrafts,
  registerLeaveGuard,
  retainDraft,
} from "../app/src/state/leaveGuards.ts";
import type { GuidedPreferences } from "../app/src/api/contracts.ts";
import {
  mergeInvestigationSettings,
  onlyInvestigationSettingsChanged,
} from "../app/src/features/guided/speakerSetup.ts";

const turn = () => new Promise<void>((resolve) => setImmediate(resolve));
const unexpected = (error: unknown) => {
  throw error;
};

test("navigation waits for the latest draft, including edits during a pending write", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const pending = Promise.withResolvers<void>();
  const writes: string[] = [];
  const session = new DraftSession<string>(async (value) => {
    writes.push(value);
    if (writes.length === 1) await pending.promise;
  }, unexpected);
  session.adopt("saved", "recovered");
  assert.equal(session.getSnapshot().dirty, true);
  session.edit("first edit");
  const unregister = registerLeaveGuard(session.flush);
  t.after(unregister);
  const leaving = flushDrafts();
  await turn();
  session.edit("latest edit");
  pending.resolve();
  await leaving;
  assert.deepEqual(writes, ["first edit", "latest edit"]);
  assert.equal(session.getSnapshot().value, "latest edit");
  assert.equal(session.getSnapshot().dirty, true);
  await session.dispose();
});

test("autosaved writes become the clean baseline only once the latest edit is written", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const pending = Promise.withResolvers<void>();
  const writes: [string, boolean][] = [];
  const session: DraftSession<string> = new DraftSession<string>(
    async (value) => {
      writes.push([value, session.getSnapshot().dirty]);
      if (writes.length === 1) await pending.promise;
    },
    unexpected,
    { autosave: true },
  );
  session.adopt("saved");
  session.edit("first edit");
  const saving = session.flush();
  await turn();
  session.edit("latest edit");
  pending.resolve();
  await saving;
  assert.deepEqual(writes, [
    ["first edit", true],
    ["latest edit", true],
  ]);
  assert.equal(session.getSnapshot().dirty, false);
  await session.dispose();
});

test("discard clears the stored draft after a write already under way", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const writing = Promise.withResolvers<void>();
  let stored: string | null = null;
  const session = new DraftSession<string>(async (value) => {
    await writing.promise;
    stored = value;
  }, unexpected);
  session.adopt("saved");
  session.edit("edit");
  t.mock.timers.tick(400);
  await turn();
  const discarding = session.discard("saved", async () => {
    stored = null;
  });
  writing.resolve();
  await discarding;
  assert.equal(stored, null);
  assert.equal(session.getSnapshot().dirty, false);
});

test("edits during an explicit save survive with the new saved revision", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  type Value = { text: string; revision: string };
  const writes: Value[] = [];
  const pending = Promise.withResolvers<{ saved: Value }>();
  const session = new DraftSession<Value>(async (value) => {
    writes.push(value);
  }, unexpected);
  session.adopt({ text: "saved", revision: "1" });
  session.edit({ text: "first edit", revision: "1" });
  const saving = session.commit(
    () => pending.promise,
    (_before, current, result) => ({
      ...current,
      revision: result.saved.revision,
    }),
  );
  await turn();
  assert.equal(session.getSnapshot().committing, true);
  session.edit({ text: "newer edit", revision: "1" });
  pending.resolve({ saved: { text: "first edit", revision: "2" } });
  await saving;
  assert.deepEqual(session.getSnapshot(), {
    value: { text: "newer edit", revision: "2" },
    dirty: true,
    committing: false,
  });
  assert.deepEqual(writes.at(-1), { text: "newer edit", revision: "2" });
  await session.dispose();
});

test("a failed recovery write blocks leaving and remains retryable after the editor unmounts", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let fail = true;
  const writes: string[] = [];
  const session = new DraftSession<string>(async (value) => {
    if (fail) throw new Error("No space");
    writes.push(value);
  }, unexpected);
  session.adopt("saved");
  session.edit("keep this edit");
  const release = retainDraft(session);
  t.after(async () => {
    fail = false;
    await release();
  });
  await assert.rejects(flushDrafts(), /No space/);
  await assert.rejects(release(), /No space/);
  await assert.rejects(flushDrafts(), /No space/);
  assert.equal(session.getSnapshot().dirty, true);
  assert.equal(session.getSnapshot().value, "keep this edit");
  fail = false;
  await flushDrafts();
  assert.deepEqual(writes, ["keep this edit"]);
  await flushDrafts();
  assert.deepEqual(writes, ["keep this edit"]);
  await session.dispose();
});

test("investigation settings merge without losing file, width, or rule edits made during application", async () => {
  const before: GuidedPreferences = {
    revision: 1,
    values: {
      selected: ["Map001.json"],
      mode: "batch",
      phase1_comments: false,
      widths: { width: 50, faceWidth: 40, listWidth: 50, noteWidth: 50 },
      engine_options: { INLINE401SPEAKERS: false, FIRSTLINESPEAKERS: false },
    },
  };
  const pending = Promise.withResolvers<{ saved: GuidedPreferences }>();
  const writes: GuidedPreferences[] = [];
  const session = new DraftSession<GuidedPreferences>(async (value) => {
    writes.push(value);
  }, unexpected);
  session.adopt(before);
  const saving = session.commit(
    () => pending.promise,
    (before, current, result) =>
      mergeInvestigationSettings(before, current, result.saved),
  );
  await turn();
  session.edit({
    ...before,
    values: {
      ...before.values,
      selected: ["Map002.json"],
      widths: { ...before.values.widths, width: 60 },
      engine_options: {
        ...before.values.engine_options,
        FIRSTLINESPEAKERS: true,
      },
    },
  });
  pending.resolve({
    saved: {
      ...before,
      revision: 2,
      values: {
        ...before.values,
        widths: { ...before.values.widths, width: 55 },
        engine_options: { INLINE401SPEAKERS: true, FIRSTLINESPEAKERS: false },
      },
    },
  });
  await saving;
  assert.deepEqual(writes.at(-1)?.values, {
    ...before.values,
    selected: ["Map002.json"],
    widths: { ...before.values.widths, width: 60 },
    engine_options: { INLINE401SPEAKERS: true, FIRSTLINESPEAKERS: true },
  });
  assert.equal(session.getSnapshot().value?.revision, 2);
  assert.equal(session.getSnapshot().dirty, true);
  const changed = {
    ...before,
    revision: 2,
    values: {
      ...before.values,
      widths: { ...before.values.widths, width: 55 },
      engine_options: {
        ...before.values.engine_options,
        INLINE401SPEAKERS: true,
      },
    },
  };
  const selected = {
    ...before,
    values: { ...before.values, selected: ["Map002.json"] },
  };
  const measured = mergeInvestigationSettings(before, selected, changed);
  assert.equal(measured.values.widths.width, 55);
  assert.deepEqual(measured.values.selected, selected.values.selected);
  assert.equal(
    onlyInvestigationSettingsChanged(before, changed, ["INLINE401SPEAKERS"]),
    true,
  );
  assert.equal(
    onlyInvestigationSettingsChanged(
      before,
      { ...changed, values: { ...changed.values, selected: ["Map003.json"] } },
      ["INLINE401SPEAKERS"],
    ),
    false,
  );
  await session.dispose();
});
