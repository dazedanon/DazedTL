import assert from "node:assert/strict";
import test from "node:test";
import type { Document } from "../app/src/api/contracts.ts";
import {
  documentStatus,
  draftsRefusal,
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
  ...values,
});

test("each method's editor reads a document's state the same way, a file changed under a draft included", () => {
  // Assistant-led showed only Draft where Guided showed Saved, None yet and
  // Unsaved edits, and neither said a file changed on disk under a draft.
  const saved = { state: "saved" as const, text: "Mine", revision: "a" };
  const cases: [string, Partial<Document>, string | undefined, string][] = [
    ["missing", {}, undefined, "missing"],
    ["saved", saved, undefined, "saved"],
    ["unreadable", { state: "unreadable", revision: "" }, "a", "unreadable"],
    ["a draft", saved, "a", "draft"],
    [
      "changed on disk",
      { ...saved, text: "Theirs", revision: "b" },
      "a",
      "changed",
    ],
    ["deleted on disk", {}, "a", "changed"],
    ["created on disk", { ...saved, text: "Theirs" }, "", "changed"],
    ["a draft of a missing file", {}, "", "draft"],
    ["a file holding the draft", { ...saved, revision: "b" }, "a", "draft"],
  ];
  for (const [label, values, began, expected] of cases)
    assert.equal(
      documentStatus(
        document("notes", values),
        began === undefined ? undefined : { text: "Mine", revision: began },
      ),
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
