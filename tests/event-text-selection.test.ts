import assert from "node:assert/strict";
import test from "node:test";
import { filteredChoices, toggleChoice, sourceErrors, selectorKeys } from "../app/src/features/guided/eventTextSelection.ts";
import type { EventTextState } from "../app/src/api/contracts.ts";

test("registry filtering preserves exact hidden selections and keeps plugin and script targets independent", () => {
  // Protect slash/case-sensitive registry IDs and hidden selections through
  // search, Selected/Recommended filters and repeated checkbox changes.
  const choices = [{ id: "build/ARPG_Core", group: "Plugins", details: "Text, SkillByName" },
    { id: "TextPicture", group: "Plugins", details: "text" }];
  const before = ["build/ARPG_Core", "TextPicture"];
  assert.deepEqual(filteredChoices(choices, before, ["TextPicture"], "textpicture", "selected").map((row) => row.id), ["TextPicture"]);
  assert.deepEqual(filteredChoices(choices, before, ["TextPicture"], "", "recommended").map((row) => row.id), ["TextPicture"]);
  assert.deepEqual(toggleChoice(before, "TextPicture", false), ["build/ARPG_Core"]);
  assert.deepEqual(before, ["build/ARPG_Core", "TextPicture"]);
  const script = ["$gameVariables._data"];
  const values = { [selectorKeys.CODE357]: toggleChoice(before, "TextPicture", false), [selectorKeys.CODE355655]: script };
  assert.deepEqual(values.ENABLED_PLUGINS_357, ["build/ARPG_Core"]);
  assert.deepEqual(values.ENABLED_PATTERNS_355655, ["$gameVariables._data"]);
});

test("source readiness rejects unknown or empty selectors while exposing actual built-in coverage", () => {
  const state = { rows: [{ key: "CODE357", label: "MZ", selector: "ENABLED_PLUGINS_357", choices: [{ id: "TextPicture" }] }], builtinHits: { CODE357: [] } } as unknown as EventTextState;
  const values = { CODE357: true, ENABLED_PLUGINS_357: [] as string[] };
  assert.equal(sourceErrors(state, values).length, 1);
  values.ENABLED_PLUGINS_357 = ["mock-placeholder"];
  assert.equal(sourceErrors(state, values).length, 1);
  values.ENABLED_PLUGINS_357 = ["TextPicture"];
  assert.deepEqual(sourceErrors(state, values), []);
  values.ENABLED_PLUGINS_357 = [];
  state.builtinHits.CODE357 = ["LL_GalgeChoiceWindow"];
  assert.deepEqual(sourceErrors(state, values), []);
});
