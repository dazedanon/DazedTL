import assert from "node:assert/strict";
import { test } from "node:test";
import {
  gridStep,
  idsBetween,
  virtualRows,
} from "../app/src/features/images/imageSelection.ts";

test("image Shift ranges read past the loaded pages within the list's read limit", async () => {
  // Protect against a range stopping at the mounted tiles or asking the
  // backend for more images than one read returns.
  const ids = Array.from({ length: 1200 }, (_, index) => `img/${index}.png`);
  const loaded = (index: number) =>
    index < 100 || index >= 1100 ? ids[index] : undefined;
  assert.deepEqual(
    idsBetween(10, 20, loaded, () => assert.fail()),
    [...ids.slice(10, 21)],
  );
  const reads: [number, number][] = [];
  const range = await idsBetween(50, 1150, loaded, async (offset, limit) => {
    reads.push([offset, limit]);
    return ids.slice(offset, offset + limit);
  });
  assert.deepEqual(range, ids.slice(50, 1151));
  assert.deepEqual(reads, [
    [100, 500],
    [600, 500],
  ]);
  // Images removed since the grid loaded end the range early.
  const short = await idsBetween(90, 120, loaded, async () => ["img/new.png"]);
  assert.deepEqual(short, [...ids.slice(90, 100), "img/new.png"]);
});

test("large image grids keep a bounded visible range and recover stale scroll positions", () => {
  const range = virtualRows(30000, 12, 114, 125000, 650);
  assert.ok(range.end - range.start <= 12 * (Math.ceil(650 / 114) + 5));
  assert.equal(range.start % 12, 0);
  assert.equal(range.top, (range.start / 12) * 114);
  assert.equal(range.height, 2500 * 114);
  const reduced = virtualRows(3, 12, 114, 125000, 650);
  assert.equal(reduced.start, 0);
  assert.equal(reduced.end, 3);
  assert.deepEqual(virtualRows(0, 12, 114, 0, 650), {
    start: 0,
    end: 0,
    top: 0,
    height: 0,
  });
  // Arrow keys stay in the grid: down into a shorter last row ends on its
  // last tile, and up from the first row stays put.
  assert.equal(gridStep("ArrowDown", 13, 12, 30), 25);
  assert.equal(gridStep("ArrowDown", 23, 12, 30), 29);
  assert.equal(gridStep("ArrowDown", 25, 12, 30), 25);
  assert.equal(gridStep("ArrowUp", 5, 12, 30), 5);
  assert.equal(gridStep("End", 5, 12, 30), 29);
});
