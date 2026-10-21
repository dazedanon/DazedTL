import assert from "node:assert/strict";
import test from "node:test";
import { widthsSaveNotice } from "../app/src/features/guided/lineWidths.ts";

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
