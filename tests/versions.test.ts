import assert from "node:assert/strict";
import test from "node:test";
import type {
  TranslationJob,
  TranslationState,
} from "../app/src/api/contracts.ts";
import {
  versionSession,
  updateCounts,
} from "../app/src/features/translation/versionState.ts";

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
