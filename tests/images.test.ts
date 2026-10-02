import assert from "node:assert/strict";
import { test } from "node:test";
import { toggleImage, virtualRows } from "../app/src/features/images/imageSelection.ts";

test("image selection preserves hidden assets when visible selections change", () => {
  const selected = ["img/system/menu.png", "img/pictures/hidden.png"];
  assert.deepEqual(toggleImage(selected, "img/system/menu.png", false), ["img/pictures/hidden.png"]);
  assert.deepEqual(toggleImage(selected, "img/system/menu.png", true), selected);
  assert.deepEqual(selected, ["img/system/menu.png", "img/pictures/hidden.png"]);
});

test("large image grids keep a bounded visible range and recover stale scroll positions", () => {
  const range = virtualRows(30000, 12, 114, 125000, 650);
  assert.ok(range.end - range.start <= 12 * (Math.ceil(650 / 114) + 5));
  assert.equal(range.start % 12, 0);
  assert.equal(range.top, range.start / 12 * 114);
  assert.equal(range.height, 2500 * 114);
  const reduced = virtualRows(3, 12, 114, 125000, 650);
  assert.equal(reduced.start, 0);
  assert.equal(reduced.end, 3);
  assert.deepEqual(virtualRows(0, 12, 114, 0, 650), { start: 0, end: 0, top: 0, height: 0 });
});
