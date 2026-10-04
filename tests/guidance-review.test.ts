import assert from "node:assert/strict";
import test from "node:test";
import type { ContextSetup, Documents } from "../app/src/api/contracts.ts";
import { guidanceAvailability, guidanceNames, saveGuidanceSet } from "../app/src/features/guided/guidanceReview.ts";

test("guidance completion follows file presence independently of old review and investigation state", () => {
  const setup = { status: "stale", documents: Object.fromEntries(["glossary", "quirks", "game"].map(name => [name,
    { exists: true, reviewed: false, needsReview: true, intentionalEmpty: false }])) } as ContextSetup;
  for (const status of ["missing", "waiting", "ready", "stale", "invalid"] as const) {
    setup.status = status;
    assert.deepEqual(guidanceAvailability(setup.documents), { complete: true, missing: [] });
  }
  setup.documents.game.exists = false;
  assert.deepEqual(guidanceAvailability(setup.documents), { complete: false, missing: ["game"] });
  assert.equal(guidanceAvailability({}).complete, false);
  setup.documents.game.exists = true;
  setup.documents["custom:notes"] = { exists: false, reviewed: false, needsReview: false, intentionalEmpty: false };
  assert.equal(guidanceAvailability(setup.documents).complete, true);
  assert.ok(guidanceNames({}, { "custom:notes": { text: "", revision: "old" } }).includes("custom:notes"));
});

test("a partial guidance save reports committed portions and leaves remaining drafts for retry", async () => {
  const pending: Documents = { glossary: { text: "薬 (Potion)", revision: "g" }, quirks: { text: "Retained voice draft.", revision: "q" }, game: { text: "Retained game draft.", revision: "c" } };
  const save = async (name: string) => {
    if (name === "quirks") throw new Error("Disk write failed.");
    const saved = { [name]: pending[name] }; delete pending[name]; return saved;
  };
  await assert.rejects(saveGuidanceSet(["glossary", "quirks", "game"], save), /Saved Glossary.*Disk write failed.*Remaining drafts/);
  assert.equal(pending.quirks.text, "Retained voice draft.");
  assert.equal(pending.game.text, "Retained game draft.");
  assert.equal(pending.glossary, undefined);
});
