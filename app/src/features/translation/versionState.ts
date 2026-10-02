import type { TranslationJob, TranslationState } from "../../api/contracts.ts";

export const versionActions = new Set(["stage_update", "version_preview", "version_apply", "version_continue", "version_abort", "version_handoff"]);

export function updateCounts(value: Record<string, unknown>) {
  const count = (key: string) => Array.isArray(value[key]) ? value[key].length : 0;
  const assets: { change?: string }[] = Array.isArray(value.external_changes) ? value.external_changes : [];
  return { added: count("added_paths") + assets.filter((row) => row.change === "Added").length,
    changed: count("modified_paths") + assets.filter((row) => ["Replaced", "Modified"].includes(row.change || "")).length,
    removed: count("deleted_paths") + assets.filter((row) => row.change === "Removed").length };
}

/** Only the latest preparation attempt can supply the update offered for review. */
export function versionSession(jobs: TranslationJob[], git: TranslationState["git"]) {
  const history = jobs.filter((job) => job.kind === "operation" && versionActions.has(job.action || ""));
  const stageIndex = history.findIndex((job) => job.action === "stage_update");
  const current = stageIndex < 0 ? history : history.slice(0, stageIndex + 1);
  const stage = current.find((job) => job.action === "stage_update");
  const candidate = current.find((job) => job.action === "version_preview");
  const mutation = current.find((job) => ["stage_update", "version_apply", "version_continue", "version_abort"].includes(job.action || ""));
  const finished = mutation?.status === "complete" && ["version_apply", "version_continue"].includes(mutation.action || "") && mutation.result?.complete === true;
  const aborted = mutation?.action === "version_abort" && mutation.status === "complete";
  const matchesStage = !stage || stage.status === "complete" && candidate?.result?.source_root === stage.result?.official && candidate?.result?.version === stage.result?.version;
  const preview = candidate?.status === "complete" && candidate.result?.proposed_tree && matchesStage && !finished && !aborted ? candidate : undefined;
  const stale = !!preview && (!git?.worktree_clean || preview.result?.original_commit !== git?.original_commit || preview.result?.translation_commit !== git?.translation_commit);
  return { history, current, latest: current[0], stage, preview, stale, finished, aborted,
    handoff: current.find((job) => job.action === "version_handoff" && job.status === "complete" && typeof job.result?.prompt === "string") };
}
