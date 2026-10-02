import assert from "node:assert/strict";
import test from "node:test";
import type { ContextSetup, Documents } from "../app/src/api/contracts.ts";
import { guidanceBlockers, guidanceNames, guidanceStatus, saveGuidanceSet } from "../app/src/features/guided/guidanceReview.ts";

test("hidden guidance blocks review until explicit empty choices or draft conflicts are resolved", () => {
  const documents = { glossary: { text: "名前 (Name)", revision: "g" }, quirks: { text: "Use informal speech.", revision: "q" }, game: { text: "", revision: "empty" }, "custom:rules": { text: "Extra rules.", revision: "c" } };
  const setup = { documents: { glossary: { exists: true }, quirks: { exists: true }, game: { exists: false }, "custom:rules": { exists: true } } } as unknown as ContextSetup;
  const drafts: Documents = { glossary: { text: "名前 (New name)", revision: "g" }, quirks: { text: "Keep this draft.", revision: "older" } };
  const names = guidanceNames(documents, drafts);
  assert.deepEqual(guidanceBlockers(names, documents, drafts, setup), ["quirks", "game"]);
  assert.equal(guidanceStatus("glossary", documents, drafts, setup), "Draft");
  setup.documents.game = { exists: true, reviewed: true, needsReview: false, intentionalEmpty: true };
  delete drafts.quirks;
  assert.deepEqual(guidanceBlockers(names, documents, drafts, setup), []);
  drafts.game = { text: "", revision: "empty" };
  assert.deepEqual(guidanceBlockers(names, documents, drafts, setup), ["game"]);
  drafts.game.text = "New game context.";
  assert.deepEqual(guidanceBlockers(names, documents, drafts, setup), []);
});

test("a partial guidance save reports committed portions and leaves remaining drafts for retry", async () => {
  const pending: Documents = { glossary: { text: "薬 (Potion)", revision: "g" }, quirks: { text: "Retained voice draft.", revision: "q" }, game: { text: "Retained game draft.", revision: "c" } };
  const reviewed: string[] = [];
  const save = async (name: string) => {
    if (name === "quirks") throw new Error("Disk write failed.");
    const saved = { [name]: pending[name] }; delete pending[name]; return saved;
  };
  await assert.rejects(saveGuidanceSet(["glossary", "quirks", "game"], save, async (name) => { reviewed.push(name); }), /Saved Glossary.*Disk write failed.*Remaining drafts/);
  assert.deepEqual(reviewed, ["glossary"]);
  assert.equal(pending.quirks.text, "Retained voice draft.");
  assert.equal(pending.game.text, "Retained game draft.");
  assert.equal(pending.glossary, undefined);
});
