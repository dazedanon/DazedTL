import assert from "node:assert/strict";
import test from "node:test";
import type { Document } from "../app/src/api/contracts.ts";
import {
  documentStatus,
  draftsRefusal,
  savedMessage,
  unreadableLeftOut,
} from "../app/src/state/documentState.ts";
import { lineDiff } from "../app/src/ui/lineDiff.ts";

const document = (
  key: "glossary" | "notes",
  values: Partial<Document>,
): Document => ({
  text: "",
  revision: "empty",
  path: "/game/" + key,
  file: key,
  title: key === "notes" ? "Assistant notes" : "Glossary",
  kind: key === "notes" ? "optional" : "core",
  requests: key !== "notes",
  holdsUp: key === "notes" ? ["handoff"] : ["handoff", "work"],
  state: "missing",
  changed: false,
  ...values,
});

test("each method's editor reads a document's state the same way, a file changed under a draft included", () => {
  // Assistant-led showed only Draft where Guided showed Saved, None yet and
  // Unsaved edits, and neither said a file changed on disk under a draft;
  // the backend decides that, as its save refuses.
  const draft = { text: "Mine", revision: "a" };
  const cases: [string, Partial<Document>, boolean, string][] = [
    ["missing", {}, false, "missing"],
    ["saved", { state: "saved" }, false, "saved"],
    ["a draft", { state: "saved" }, true, "draft"],
    ["changed on disk", { state: "saved", changed: true }, true, "changed"],
    ["unreadable", { state: "unreadable", changed: true }, true, "unreadable"],
  ];
  for (const [label, values, drafted, expected] of cases)
    assert.equal(
      documentStatus(document("notes", values), drafted ? draft : undefined),
      expected,
      label,
    );
});

test("a draft holds up only the work its definition names, saying which tab saves it", () => {
  // A notes draft held up estimates, runs and every helper operation.
  const documents = {
    glossary: document("glossary", {}),
    notes: document("notes", {}),
  };
  const notes = { notes: { text: "Mine", revision: "" } };
  assert.equal(draftsRefusal(documents, notes, "work", "Guidance"), "");
  assert.equal(
    draftsRefusal(documents, notes, "handoff", "Context"),
    "Save or discard your Assistant notes draft in Context first.",
  );
  assert.equal(
    draftsRefusal(
      documents,
      { ...notes, glossary: { text: "", revision: "" } },
      "handoff",
      "Guidance",
    ),
    "Save or discard your Assistant notes, Glossary drafts in Guidance first.",
  );
});

test("the changed-on-disk choice compares the draft with the file in hunks TextDiff reads", () => {
  const file = ["# Quirks", "a", "b", "c", "d", "e", "f", "g", "h", "end"];
  const draft = [
    "# Quirks",
    "a",
    "B",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "end",
    "new",
  ];
  assert.equal(
    lineDiff(file.join("\n"), draft.join("\n")),
    [
      "@@ -1,6 +1,6 @@",
      " # Quirks",
      " a",
      "-b",
      "+B",
      " c",
      " d",
      " e",
      "@@ -8,3 +8,4 @@",
      " g",
      " h",
      " end",
      "+new",
    ].join("\n"),
  );
  assert.equal(lineDiff("same", "same"), "");
});

test("a save says which files it left out unread, and never that guidance is saved while one is", () => {
  // A core file DazedTL can't read kept Guidance incomplete while Save
  // guidance said "Guidance is already saved.".
  const documents = {
    glossary: document("glossary", { state: "saved" }),
    game: {
      ...document("glossary", { state: "unreadable" }),
      file: ".dazedtl/skills/game.md",
    },
    notes: document("notes", { state: "unreadable" }),
  };
  const drafts = { notes: { text: "Mine", revision: "" } };
  const whole = unreadableLeftOut(documents, drafts, ["notes"], true);
  assert.deepEqual(whole, ["game", "notes"]);
  assert.deepEqual(unreadableLeftOut(documents, {}, [], false), []);
  assert.equal(
    savedMessage("Guidance", { documents, saved: [] }, [], ["game"], documents),
    "DazedTL can't read .dazedtl/skills/game.md; its tab says why.",
  );
  assert.equal(
    savedMessage(
      "Guidance",
      { documents, saved: ["glossary"] },
      [],
      whole,
      documents,
    ),
    "Guidance saved. DazedTL can't read .dazedtl/skills/game.md, notes; their tabs say why.",
  );
  assert.equal(
    savedMessage("Guidance", { documents, saved: [] }, [], [], documents),
    "Guidance is already saved.",
  );
  assert.equal(
    savedMessage("Context", null, [], [], documents),
    "Nothing to save.",
  );
});
