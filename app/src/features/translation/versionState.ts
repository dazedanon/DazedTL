import type {
  ReleaseLayout,
  TranslationJob,
  TranslationState,
  VersionRecord,
} from "../../api/contracts.ts";
import { displayText } from "../../ui/displayText.ts";

const files = (count: number) =>
  `${count.toLocaleString()} ${count === 1 ? "file" : "files"}`;

/** The game's files a complete release leaves out, which applying it removes. */
export const removedFiles = (layout: ReleaseLayout) =>
  layout.kind === "game" ? layout.game_files - layout.covered : 0;

/** What a release does to the game when applied as its layout's kind. */
export function releaseEffect(layout: ReleaseLayout) {
  if (layout.kind === "game") {
    const removed = removedFiles(layout);
    return removed
      ? `Replaces the game. ${removed.toLocaleString()} of the game’s ${files(layout.game_files)} aren’t in it and would be removed.`
      : "Replaces the game with this release.";
  }
  const added = layout.files - layout.replaced;
  const copied = !layout.replaced
    ? `Adds ${files(added)} to the game.`
    : !added
      ? `Replaces ${files(layout.replaced)} in the game.`
      : `Replaces ${files(layout.replaced)} and adds ${added.toLocaleString()} new.`;
  return `${copied} Everything else stays.`;
}

/** Where a release's files go when they don't line up with the game as chosen. */
export function releasePlacement(layout: ReleaseLayout) {
  // The layout names only the first few files it leaves out.
  const leftOut =
    layout.outside > 3
      ? `${layout.left_out.slice(0, 2).join(", ")} and ${(layout.outside - 2).toLocaleString()} more`
      : layout.left_out.join(", ");
  const parts = [
    layout.source && `uses the “${layout.source}” folder inside it`,
    layout.target && `puts its files in the game’s “${layout.target}” folder`,
    layout.outside &&
      `leaves out ${layout.outside === 1 ? "the file" : `the ${files(layout.outside)}`} beside that folder: ${leftOut}`,
  ].filter(Boolean) as string[];
  if (!parts.length) return "";
  const text =
    parts.length > 1
      ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`
      : parts[0];
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
}

/** The layout a stage job used, which older stages do not record. */
export function stagedLayout(job: TranslationJob | undefined) {
  const layout = job?.result?.layout;
  return layout && typeof layout === "object"
    ? (layout as ReleaseLayout)
    : undefined;
}

export const versionActions = new Set([
  "stage_update",
  "version_preview",
  "version_apply",
  "version_continue",
  "version_abort",
  "version_handoff",
]);

export function updateCounts(value: Record<string, unknown>) {
  const count = (key: string) =>
    Array.isArray(value[key]) ? value[key].length : 0;
  const assets: { change?: string }[] = Array.isArray(value.external_changes)
    ? value.external_changes
    : [];
  return {
    added:
      count("added_paths") +
      assets.filter((row) => row.change === "Added").length,
    changed:
      count("modified_paths") +
      assets.filter((row) =>
        ["Replaced", "Modified"].includes(row.change || ""),
      ).length,
    removed:
      count("deleted_paths") +
      assets.filter((row) => row.change === "Removed").length,
  };
}
/** The update's added, changed and removed file counts in words, without zeros. */
export function updateSummary(value: Record<string, unknown>) {
  const counts = updateCounts(value);
  return (
    [
      ["added", counts.added],
      ["changed", counts.changed],
      ["removed", counts.removed],
    ] as const
  )
    .filter(([, count]) => count)
    .map(([label, count]) => `${count.toLocaleString()} ${label}`)
    .join(" · ");
}

/** Only the latest preparation attempt can supply the update offered for review. */
export function versionSession(
  jobs: TranslationJob[],
  git: TranslationState["git"],
  /** The staged release the user discarded, which no longer opens a review. */
  discarded?: string,
) {
  const history = jobs.filter(
    (job) => job.kind === "operation" && versionActions.has(job.action || ""),
  );
  const stageIndex = history.findIndex((job) => job.action === "stage_update");
  const current =
    stageIndex >= 0 && history[stageIndex].id === discarded
      ? []
      : stageIndex < 0
        ? history
        : history.slice(0, stageIndex + 1);
  const stage = current.find((job) => job.action === "stage_update");
  const candidate = current.find((job) => job.action === "version_preview");
  const mutation = current.find((job) =>
    [
      "stage_update",
      "version_apply",
      "version_continue",
      "version_abort",
    ].includes(job.action || ""),
  );
  // History alone can outlive the update: a reset or restored repository no
  // longer carries the version the job applied.
  const finished =
    mutation?.status === "complete" &&
    ["version_apply", "version_continue"].includes(mutation.action || "") &&
    mutation.result?.complete === true &&
    (!git?.original_version ||
      typeof mutation.result?.version !== "string" ||
      mutation.result.version === git.original_version);
  const aborted =
    mutation?.action === "version_abort" && mutation.status === "complete";
  const matchesStage =
    !stage ||
    (stage.status === "complete" &&
      candidate?.result?.source_root === stage.result?.official &&
      candidate?.result?.version === stage.result?.version);
  const preview =
    candidate?.status === "complete" &&
    candidate.result?.proposed_tree &&
    matchesStage &&
    !finished &&
    !aborted
      ? candidate
      : undefined;
  const stale =
    !!preview &&
    (!git?.worktree_clean ||
      preview.result?.original_commit !== git?.original_commit ||
      preview.result?.translation_commit !== git?.translation_commit);
  return {
    history,
    current,
    latest: current[0],
    stage,
    preview,
    stale,
    finished,
    aborted,
    handoff: current.find(
      (job) =>
        job.action === "version_handoff" &&
        job.status === "complete" &&
        typeof job.result?.prompt === "string",
    ),
  };
}

/** How a recorded version came in, and when: "Patch · Oct 11, 2026". */
export function versionLabel(record: VersionRecord) {
  const kind =
    record.kind === "setup"
      ? "Set up"
      : record.release === "patch"
        ? "Patch"
        : record.release === "complete"
          ? "Complete release"
          : "Update";
  const date = new Date(record.recorded).toLocaleDateString(undefined, {
    dateStyle: "medium",
  });
  return `${kind} · ${date}`;
}

/** An update's four steps, each finished one with what it did; `problem`
 * marks the current step blocked. */
export function updateSteps(
  session: ReturnType<typeof versionSession>,
  layout: ReleaseLayout | undefined,
  current: number,
  problem = "",
) {
  const staged =
    session.stage?.status === "complete" ? session.stage : undefined;
  const version = displayText(staged?.result?.version);
  const compared = session.current.find(
    (job) =>
      job.action === "version_preview" &&
      job.status === "complete" &&
      !!job.result?.proposed_tree,
  );
  const results = [
    staged &&
      `${layout?.kind === "patch" ? "Patch" : "Complete game"} ${version}`.trim(),
    compared && compareResult(compared.result!),
    session.finished && `Updated to ${version}`,
    "",
  ];
  return ["Choose release", "Compare", "Apply", "Translate new text"].map(
    (label, index) => ({
      id: label,
      label,
      ...(index === current && problem
        ? { state: "blocked" as const, detail: problem }
        : {
            detail: index < current ? results[index] || undefined : undefined,
          }),
    }),
  );
}

export type TextLine = {
  kind: "added" | "changed" | "removed" | "replaced";
  before: string | null;
  translation: string | null;
  after: string | null;
};
export type FileText = {
  path: string;
  to_translate: number;
  replaced: number;
  kept: number;
  lines: TextLine[];
  more: number;
};
export type TextChanges = {
  to_translate: number;
  replaced: number;
  kept: number;
  files: FileText[];
};

/** A preview's line view, which previews from before it existed lack. */
export function textChanges(value: Record<string, unknown>) {
  const text = value.text;
  return text &&
    typeof text === "object" &&
    Array.isArray((text as TextChanges).files)
    ? (text as TextChanges)
    : undefined;
}

const lines = (count: number) =>
  `${count.toLocaleString()} ${count === 1 ? "line" : "lines"}`;

/** What an update does to a file's text, or the whole update's, without zeros. */
export function textSummary(
  text: Pick<TextChanges, "to_translate" | "replaced" | "kept">,
) {
  return [
    text.to_translate && `${lines(text.to_translate)} to translate`,
    text.replaced &&
      `${text.replaced.toLocaleString()} ${text.replaced === 1 ? "translation goes" : "translations go"} back to Japanese`,
    text.kept &&
      `${text.kept.toLocaleString()} ${text.kept === 1 ? "translation stays" : "translations stay"}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** What a comparison found, in lines to translate when it read the text. */
function compareResult(result: Record<string, unknown>) {
  const text = textChanges(result);
  if (!text) return updateSummary(result) || "No file changes";
  return text.to_translate
    ? `${text.to_translate.toLocaleString()} ${text.to_translate === 1 ? "line" : "lines"} to translate`
    : "No new text";
}
