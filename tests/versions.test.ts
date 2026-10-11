import assert from "node:assert/strict";
import test from "node:test";
import type {
  TranslationJob,
  TranslationState,
} from "../app/src/api/contracts.ts";
import {
  guidedUpdateTasks,
  versionSession,
  updateCounts,
} from "../app/src/features/translation/versionState.ts";

test("an applied update counts as done only while the repository is at that version", () => {
  const apply = {
    id: "apply",
    kind: "operation",
    action: "version_apply",
    status: "complete",
    result: { complete: true, version: "1.10" },
  } as unknown as TranslationJob;
  const at = (version: string) =>
    ({ original_version: version }) as TranslationState["git"];
  assert.equal(versionSession([apply], at("1.10")).finished, true);
  assert.equal(versionSession([apply], at("1.00")).finished, false);
});

test("a new or failed release attempt cannot offer an older comparison for application", () => {
  const git = {
    original_commit: "original",
    translation_commit: "translated",
    worktree_clean: true,
  } as TranslationState["git"];
  const job = (
    id: string,
    action: string,
    result: Record<string, unknown> = {},
    status = "complete",
  ) => ({ id, kind: "operation", action, result, status }) as TranslationJob;
  const stage = job("stage-1", "stage_update", {
    official: "/prepared/1",
    version: "1.1",
  });
  const preview = job("preview-1", "version_preview", {
    source_root: "/prepared/1",
    version: "1.1",
    proposed_tree: "tree",
    original_commit: "original",
    translation_commit: "translated",
  });
  assert.equal(versionSession([preview, stage], git).preview?.id, preview.id);
  // A discarded release no longer offers its review.
  const discarded = versionSession([preview, stage], git, stage.id);
  assert.equal(discarded.preview, undefined);
  assert.equal(discarded.stage, undefined);
  for (const status of ["running", "failed", "complete"]) {
    const newer = job(
      "stage-2",
      "stage_update",
      { official: "/prepared/2", version: "1.2" },
      status,
    );
    assert.equal(
      versionSession([newer, preview, stage], git).preview,
      undefined,
    );
    assert.equal(
      versionSession([preview, newer, stage], git).preview,
      undefined,
    );
  }
  assert.equal(
    versionSession(
      [job("failed-preview", "version_preview", {}, "failed"), preview, stage],
      git,
    ).preview,
    undefined,
  );
  for (const change of [
    { original_commit: "new-original" },
    { translation_commit: "new-translation" },
    { worktree_clean: false },
  ]) {
    assert.equal(
      versionSession([preview, stage], { ...git!, ...change }).stale,
      true,
    );
  }
  const applied = job("apply", "version_apply", { complete: true });
  assert.equal(
    versionSession([applied, preview, stage], git).preview,
    undefined,
  );
  assert.equal(versionSession([applied, preview, stage], git).finished, true);
  assert.equal(
    versionSession([job("abort", "version_abort"), preview, stage], git)
      .preview,
    undefined,
  );
  assert.equal(
    versionSession(
      [job("stage-2", "stage_update", {}, "running"), applied, preview, stage],
      git,
    ).finished,
    false,
  );
  // Loose images/audio still change the game and must appear in review totals.
  assert.deepEqual(
    updateCounts({
      added_paths: [],
      modified_paths: ["Map001.json"],
      deleted_paths: [],
      external_changes: [
        { change: "Added", path: "img/new.png" },
        { change: "Replaced", path: "audio/theme.ogg" },
        { change: "Removed", path: "img/old.png" },
      ],
    }),
    { added: 1, changed: 2, removed: 1 },
  );
});

test("a finished update opens the Guided tasks its files belong to", () => {
  // MV keeps its data under www/, a new map is not listed by Guided yet, and
  // removed or unchanged files need no translating.
  const tasks = guidedUpdateTasks(
    {
      file_changes: [
        { path: "www/data/Map001.json", change: "Modified" },
        { path: "www/data/Actors.json", change: "Modified" },
        { path: "www/data/Map003.json", change: "Removed" },
        { path: "www/js/plugins.js", change: "Modified" },
        {
          path: "www/data/System.json",
          change: "Modified",
          already_present: true,
        },
      ],
      external_changes: [
        { path: "www/data/Map002.json", change: "Added" },
        { path: "www/img/pictures/sign.png", change: "Replaced" },
        { path: "www/audio/bgm/theme.ogg", change: "Replaced" },
      ],
      text: {
        to_translate: 5,
        replaced: 0,
        kept: 0,
        files: [
          {
            path: "www/data/Map001.json",
            to_translate: 3,
            replaced: 0,
            kept: 0,
            lines: [],
            more: 0,
          },
          {
            path: "www/data/Map002.json",
            to_translate: 2,
            replaced: 0,
            kept: 0,
            lines: [],
            more: 0,
          },
        ],
      },
    },
    new Map([
      ["Map001.json", "dialogue"],
      ["Actors.json", "database"],
    ]),
  );
  assert.deepEqual(
    tasks.map(({ task, files, lines }) => ({ task, files, lines })),
    [
      { task: "database", files: ["Actors.json"], lines: 0 },
      { task: "dialogue", files: ["Map001.json", "Map002.json"], lines: 5 },
      { task: "plugins", files: ["plugins.js"], lines: 0 },
      { task: "images", files: ["www/img/pictures/sign.png"], lines: 0 },
    ],
  );
});
