import assert from "node:assert/strict";
import test from "node:test";
import type { ContextSetup, GuidedState } from "../app/src/api/contracts.ts";
import {
  guidanceAvailability,
  guidanceNames,
} from "../app/src/features/guided/guidanceReview.ts";
import {
  investigationResults,
  speakerNotice,
} from "../app/src/features/guided/contextView.ts";

test("investigation progress retains saved artifacts through settings changes and unsuccessful rescans", () => {
  const state = {
    speakerSetup: { status: "applied", reportId: "saved", rules: [] },
    speakerScan: {
      available: true,
      current: false,
      names: ["リーナ"],
      files: 1,
      job: { id: "old", status: "complete" },
    },
    contextSetup: {
      requestId: "copied",
      status: "stale",
      documents: Object.fromEntries(
        ["glossary", "quirks", "game"].map((name) => [name, { exists: true }]),
      ),
    },
  } as Pick<GuidedState, "speakerSetup" | "speakerScan" | "contextSetup">;
  assert.ok(
    investigationResults(state).every(
      (row) => row.saved && row.status === "saved",
    ),
  );
  state.speakerScan.job!.status = "running";
  let names = investigationResults(state).find((row) => row.id === "names")!;
  assert.equal(names.saved, true);
  assert.equal(names.status, "working");
  state.speakerScan.job!.status = "failed";
  names = investigationResults(state).find((row) => row.id === "names")!;
  assert.equal(names.saved, true);
  assert.equal(names.status, "saved");
  state.speakerScan.available = false;
  names = investigationResults(state).find((row) => row.id === "names")!;
  assert.equal(names.saved, false);
  assert.equal(names.status, "failed");
  state.speakerScan.job!.status = "complete";
  state.speakerScan.issue = "Saved file missing";
  assert.equal(
    investigationResults(state).find((row) => row.id === "names")!.status,
    "unavailable",
  );
  state.contextSetup.documents.game.exists = false;
  assert.equal(
    investigationResults(state).find((row) => row.id === "guidance")!.saved,
    false,
  );
});

test("Maps & events warns about speakers until a saved scan found names, whatever formats were enabled", () => {
  const state = {
    speakerSetup: { status: "missing", reportId: null, rules: [] },
    speakerScan: { available: false, current: false, names: [], job: null },
    contextSetup: { documents: {} },
  } as unknown as Pick<
    GuidedState,
    "speakerSetup" | "speakerScan" | "contextSetup"
  >;
  assert.match(speakerNotice(state), /^Speakers aren't set up\./);
  // Every optional format skipped, as for a game with no speakers.
  state.speakerSetup = {
    ...state.speakerSetup,
    status: "applied",
    reportId: "saved",
  };
  state.speakerScan.available = true;
  assert.match(speakerNotice(state), /^No speakers found\./);
  // MZ's own name box needs no optional format.
  state.speakerScan.names = ["村長"];
  assert.equal(speakerNotice(state), "");
  // A rescan that did not finish keeps the saved names.
  state.speakerScan.job = { status: "failed" } as never;
  assert.equal(speakerNotice(state), "");
});

test("guidance completion follows file presence independently of old review and investigation state", () => {
  const setup = {
    status: "stale",
    documents: Object.fromEntries(
      ["glossary", "quirks", "game"].map((name) => [
        name,
        {
          exists: true,
          reviewed: false,
          needsReview: true,
          intentionalEmpty: false,
        },
      ]),
    ),
  } as ContextSetup;
  assert.deepEqual(guidanceAvailability(setup.documents), {
    complete: true,
    missing: [],
  });
  setup.documents.game.exists = false;
  assert.deepEqual(guidanceAvailability(setup.documents), {
    complete: false,
    missing: ["game"],
  });
  assert.equal(guidanceAvailability({}).complete, false);
  setup.documents.game.exists = true;
  setup.documents["custom:notes"] = {
    exists: false,
    reviewed: false,
    needsReview: false,
    intentionalEmpty: false,
  };
  assert.equal(guidanceAvailability(setup.documents).complete, true);
  assert.ok(
    guidanceNames(
      {},
      { "custom:notes": { text: "", revision: "old" } },
    ).includes("custom:notes"),
  );
});
