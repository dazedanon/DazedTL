import assert from "node:assert/strict";
import test from "node:test";
import { FeedbackStore } from "../app/src/ui/feedbackStore.ts";

// A build's success beside its button repeated the Done its archive's
// heading showed; the control leaves it out only while a heading for the
// same action says the work finished.
test("a control's success shows once, where a heading says it is done", () => {
  const store = new FeedbackStore();
  assert.equal(store.saysDone("release_patch"), false);

  const outdated = store.report("release_patch", "outdated");
  assert.equal(store.saysDone("release_patch"), false);

  const done = store.report("release_patch", "done");
  assert.equal(store.saysDone("release_patch"), true);
  assert.equal(store.saysDone("release"), false);

  done();
  assert.equal(store.saysDone("release_patch"), false);
  outdated();
  store.report("export_selected", "applied");
  assert.equal(store.saysDone("export_selected"), true);
});
