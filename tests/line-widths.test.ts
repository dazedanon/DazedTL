import assert from "node:assert/strict";
import test from "node:test";
import {
  fitRunning,
  widthsSaveNotice,
} from "../app/src/features/guided/lineWidths.ts";

test("saving Line widths says when With portrait was lowered to match Dialogue", () => {
  const widths = {
    width: 45,
    faceWidth: 45,
    listWidth: 70,
    noteWidth: 75,
    messageRows: 4,
  };
  const fitted = "Rewrapped 3 lines to the new Line widths.";
  const asked = { ...widths, faceWidth: 50 };
  const notice = { fitted, saved: "", asked, widths };
  assert.equal(
    widthsSaveNotice(notice),
    `${fitted} With portrait was lowered to 45 to match Dialogue.`,
  );
  // Asked within Dialogue, the save kept it.
  assert.equal(widthsSaveNotice({ ...notice, asked: widths }), fitted);
  // Widths measured since, with their own Dialogue, were not lowered by it.
  assert.equal(
    widthsSaveNotice({ ...notice, asked: { ...asked, width: 60 } }),
    fitted,
  );
  // Nothing saved in this visit reports nothing.
  assert.equal(widthsSaveNotice({ ...notice, fitted: "" }), "");
});

test("a fit counts as running from the read that starts it until it ends", () => {
  const before = { id: "old", status: "complete" };
  // The read that starts a fit names it before it lists it.
  assert.ok(fitRunning({ named: "new", opened: "old", listed: before }));
  assert.ok(
    fitRunning({
      named: "new",
      opened: "old",
      listed: { id: "new", status: "running" },
    }),
  );
  assert.ok(
    !fitRunning({
      named: "new",
      opened: "old",
      listed: { id: "new", status: "failed" },
    }),
  );
  // A fit from before this visit that the list no longer holds has ended.
  assert.ok(!fitRunning({ named: "old", opened: "old", listed: undefined }));
  assert.ok(!fitRunning({ named: null, opened: null, listed: undefined }));
});
