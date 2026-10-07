import assert from "node:assert/strict";
import test from "node:test";
import type { GuidedFile } from "../app/src/api/contracts.ts";
import {
  filterFiles,
  selectMatching,
  sortFiles,
  retainOtherScope,
} from "../app/src/features/guided/selection.ts";
import { selectItem } from "../app/src/ui/selection.ts";

test("large filtered scopes retain hidden checks and modifier ranges use the whole matching list", () => {
  // Protect against losing a different phase's selected files, and against
  // Shift ranges stopping at the currently mounted virtual rows.
  const files: GuidedFile[] = [
    { name: "Actors.json", group: "database" },
    ...Array.from({ length: 600 }, (_, index): GuidedFile => ({
      name: `Map${index + 1}.json`,
      title: index === 41 ? "Forest temple" : "",
      group: "dialogue",
    })),
  ];
  const sorted = sortFiles(files.reverse());
  const maps = filterFiles(sorted, "maps", "").map((file) => file.name);
  assert.deepEqual(maps.slice(0, 3), ["Map1.json", "Map2.json", "Map3.json"]);
  const matching = filterFiles(sorted, "maps", "10–25").map(
    (file) => file.name,
  );
  assert.equal(matching.length, 16);
  const selected = selectMatching(["Actors.json", "Map1.json"], matching, true);
  assert.equal(selected.length, 18);
  assert.deepEqual(selectMatching(selected, matching, false), [
    "Actors.json",
    "Map1.json",
  ]);
  assert.deepEqual(
    filterFiles(sorted, "maps", "forest").map((file) => file.name),
    ["Map42.json"],
  );
  assert.equal(filterFiles(sorted, "maps", "25–10").length, 0);
  const range = selectItem(
    selected,
    maps,
    "Map500.json",
    "range",
    "Map20.json",
  );
  assert.equal(range.selected.length, 481);
  assert.equal(range.anchor, "Map20.json");
  assert.equal(range.selected.includes("Actors.json"), false);
  assert.deepEqual(
    retainOtherScope(
      ["Actors.json", "Map1.json"],
      sorted.filter((file) => file.group === "dialogue"),
      ["Map2.json"],
    ),
    ["Actors.json", "Map2.json"],
  );
  assert.deepEqual(
    retainOtherScope(
      ["Actors.json", "Map1.json"],
      sorted.filter((file) => file.group === "database"),
      [],
    ),
    ["Map1.json"],
  );
  const added = selectItem(
    ["Actors.json", "Map1.json"],
    maps,
    "Map500.json",
    "add-range",
    "Map20.json",
  );
  assert.equal(added.selected.length, 483);
  assert.equal(
    selectItem(added.selected, maps, "Map500.json", "toggle", added.anchor)
      .selected.length,
    482,
  );
  assert.deepEqual(
    selectItem(selected, matching, "Map25.json", "add-range", "Map1.json")
      .selected,
    selected,
  );
  assert.deepEqual(
    selectItem(selected, matching, "not-in-filter.json", "replace", null)
      .selected,
    selected,
  );
});
