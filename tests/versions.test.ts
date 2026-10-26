import assert from "node:assert/strict";
import test from "node:test";
import type {
  Checkpoint,
  GitStatus,
  TranslationJob,
  TranslationState,
} from "../app/src/api/contracts.ts";
import {
  readKey,
  reportsBeside,
} from "../app/src/features/project/checkpoints.ts";
import {
  finishedUpdateSummary,
  guidedUpdateTasks,
  interruptedUpdate,
  textSummary,
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
  const abort = job("abort", "version_abort");
  assert.equal(versionSession([abort, preview, stage], git).preview, undefined);
  // Comparing again after the cancel offers the update again.
  const again = { ...preview, id: "preview-2" };
  assert.equal(
    versionSession([again, abort, preview, stage], git).preview?.id,
    again.id,
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
  const result = {
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
  };
  const groups = new Map([
    ["Map001.json", "dialogue"],
    ["Actors.json", "database"],
  ] as const);
  const tasks = guidedUpdateTasks(result, groups);
  assert.deepEqual(
    tasks.map(({ task, files, lines }) => ({ task, files, lines })),
    [
      { task: "database", files: ["Actors.json"], lines: 0 },
      { task: "dialogue", files: ["Map001.json", "Map002.json"], lines: 5 },
      { task: "plugins", files: ["plugins.js"], lines: 0 },
      { task: "images", files: ["www/img/pictures/sign.png"], lines: 0 },
    ],
  );
  // A file translated after Reload from game kept reading the comparison's
  // lines; it reads its own, here none left, beside a map not read yet.
  const left = (name: string) => (name === "Map001.json" ? 0 : undefined);
  const current = guidedUpdateTasks(result, groups, left);
  assert.equal(current[1].lines, 2);
  // The summary above the rows counts what they have left, not the
  // comparison's 5, and none once nothing is left.
  assert.equal(
    finishedUpdateSummary(result, current, "Japanese"),
    textSummary({ to_translate: 2, replaced: 0, kept: 0 }, "Japanese"),
  );
  assert.equal(
    finishedUpdateSummary(
      result,
      guidedUpdateTasks(result, groups, () => 0),
      "Japanese",
    ),
    "",
  );
});

test("the Checkpoints tab reads Git again only once a write moves the branch", () => {
  // Reading the timeline runs Git; a poll path that starts processes froze
  // one user's jobs, so a snapshot that changed nothing in Git keeps the read.
  const git = {
    configured: true,
    translation_commit: "a".repeat(40),
  } as GitStatus;
  const key = readKey("game", git);
  assert.equal(readKey("game", { ...git, worktree_clean: false }), key);
  assert.notEqual(
    readKey("game", { ...git, translation_commit: "b".repeat(40) }),
    key,
  );
  assert.equal(readKey("game", { ...git, configured: false }), null);
});

test("an undo's result stays beside the checkpoint it made", () => {
  // It followed whichever row was current, so a later checkpoint, such as
  // installing Forge, read "Undone; 2 files changed".
  const row = (commit: string, current: boolean) =>
    ({ commit, current }) as Checkpoint;
  const undo = {
    status: "complete",
    action: "checkpoint_undo",
    target: "applied",
    result: { files: 2, commit: "undid" },
  };
  assert.equal(reportsBeside(undo, row("undid", false)), true);
  assert.equal(reportsBeside(undo, row("forge", true)), false);
  // One that found nothing to undo made no checkpoint, and one still
  // running made none yet: each reports by the row it was started from.
  assert.equal(
    reportsBeside(
      { ...undo, result: { files: 0, commit: "forge" } },
      row("applied", false),
    ),
    true,
  );
  assert.equal(
    reportsBeside({ ...undo, status: "running" }, row("applied", false)),
    true,
  );
});

test("an Apply under way is not an interrupted update, and a stopped one is", () => {
  const stopped = {
    pending_operations: ["cherry-pick"],
    asset_sync_pending: true,
    asset_update_applied: true,
  } as TranslationState["git"];
  // Apply's own conflicts and waiting assets flashed "Finish the interrupted
  // update" with both buttons disabled.
  assert.deepEqual(interruptedUpdate(stopped, "version_apply"), {
    conflicts: false,
    assets: false,
    assetsApplied: false,
  });
  assert.deepEqual(interruptedUpdate(stopped), {
    conflicts: true,
    assets: true,
    assetsApplied: true,
  });
  assert.equal(interruptedUpdate(stopped, "version_continue").assets, true);
});
