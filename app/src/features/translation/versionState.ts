import type {
  ReleaseLayout,
  TranslationJob,
  TranslationState,
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
      ? `Replaces the game. ${removed.toLocaleString()} of the game’s ${files(layout.game_files)} ${removed === 1 ? "isn’t" : "aren’t"} in it and would be removed.`
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

/**
 * What an update left unfinished, from the repository's state. While Apply
 * runs, its own conflicts and waiting assets are steps of that run, not an
 * interruption to finish or cancel.
 */
export function interruptedUpdate(
  git: TranslationState["git"],
  activeAction?: string | null,
) {
  const applying = activeAction === "version_apply";
  const conflicts = !applying && !!git?.pending_operations.length;
  const assets = !applying && !!git?.asset_sync_pending;
  return {
    conflicts,
    assets,
    assetsApplied: assets && !!git?.asset_update_applied,
  };
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
  // A comparison made after a canceled update offers that update again.
  const aborted =
    mutation?.action === "version_abort" &&
    mutation.status === "complete" &&
    !(candidate && current.indexOf(candidate) < current.indexOf(mutation));
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
  };
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
    // The review under way says the comparison's result itself.
    compared && current > 2 && compareResult(compared.result!),
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
  // "edited" is a checkpoint's line, its text before and after.
  kind: "added" | "changed" | "removed" | "replaced" | "edited";
  before: string | null;
  translation: string | null;
  after: string | null;
};
export type FileText = {
  path: string;
  to_translate: number;
  replaced: number;
  kept: number;
  edited?: number;
  lines: TextLine[];
  more: number;
};
export type TextChanges = {
  to_translate: number;
  replaced: number;
  kept: number;
  edited?: number;
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

const noBreak = String.fromCharCode(0xa0);

/** What an update or a checkpoint does to a file's text, or to all of it,
 * without zeros; a line wraps between its parts, never inside one. A
 * translation it drops goes back to the game's *source* language. */
export function textSummary(
  text: Pick<TextChanges, "to_translate" | "replaced" | "kept" | "edited">,
  source: string,
) {
  return [
    text.edited && `${lines(text.edited)} changed`,
    text.to_translate && `${lines(text.to_translate)} to translate`,
    text.replaced &&
      `${text.replaced.toLocaleString()} ${text.replaced === 1 ? "translation goes" : "translations go"} back to ${source}`,
    text.kept &&
      `${text.kept.toLocaleString()} ${text.kept === 1 ? "translation stays" : "translations stay"}`,
  ]
    .filter(Boolean)
    .map((part) => String(part).replaceAll(" ", noBreak))
    .join(" · ");
}

/**
 * A finished update's summary: the lines its tasks still have to translate
 * (`guidedUpdateTasks`), then the translations it sent back to the
 * *source* language and kept. "No new text" when the comparison found none; "" when its lines are
 * all translated and it sent back and kept none.
 */
export function finishedUpdateSummary(
  result: Record<string, unknown>,
  tasks: UpdateTask[],
  source: string,
) {
  const text = textChanges(result);
  if (!text) return "";
  const left = tasks.reduce((sum, task) => sum + task.lines, 0);
  return (
    textSummary({ ...text, to_translate: left }, source) ||
    (text.to_translate ? "" : "No new text")
  );
}

/** What a comparison found, in lines to translate when it read the text. */
function compareResult(result: Record<string, unknown>) {
  const text = textChanges(result);
  if (!text) return updateSummary(result) || "No file changes";
  return text.to_translate
    ? `${text.to_translate.toLocaleString()} ${text.to_translate === 1 ? "line" : "lines"} to translate`
    : "No new text";
}

export type UpdateTask = {
  task: "database" | "dialogue" | "plugins" | "images";
  title: string;
  /** The files the update changed for this task, by the names it lists. */
  files: string[];
  lines: number;
};
const taskTitles: Record<UpdateTask["task"], string> = {
  database: "Database files",
  dialogue: "Maps & events",
  plugins: "Plugin files",
  images: "Images",
};
const eventFile = /^(?:Map\d+|CommonEvents|Troops)\.json$/i;

/**
 * The Guided tasks an applied update's files belong to, in workflow order:
 * data files by the group Guided lists them in, plugins and images by folder.
 * A data file's lines to translate are the ones `left` reads in the file
 * now, once it can, else the comparison's.
 */
export function guidedUpdateTasks(
  result: Record<string, unknown>,
  groups: Map<string, "database" | "dialogue">,
  left: (
    name: string,
    task: "database" | "dialogue",
  ) => number | undefined = () => undefined,
): UpdateTask[] {
  const changes = [
    ...(Array.isArray(result.file_changes) ? result.file_changes : []),
    ...(Array.isArray(result.external_changes) ? result.external_changes : []),
  ] as { path?: unknown; change?: unknown; already_present?: unknown }[];
  const lines = new Map(
    textChanges(result)?.files.map((file) => [file.path, file.to_translate]),
  );
  const tasks = new Map<UpdateTask["task"], UpdateTask>();
  for (const change of changes) {
    if (typeof change.path !== "string" || change.already_present === true)
      continue;
    if (change.change === "Removed") continue;
    const path = change.path.toLowerCase();
    const name = change.path.split("/").pop()!;
    const task: UpdateTask["task"] | undefined =
      /(?:^|\/)(?:data|ace_json)\/[^/]+\.json$/.test(path)
        ? (groups.get(name) ?? (eventFile.test(name) ? "dialogue" : "database"))
        : /(?:^|\/)js\/plugins(?:\.js$|\/)/.test(path)
          ? "plugins"
          : /(?:^|\/)img\//.test(path)
            ? "images"
            : undefined;
    if (!task) continue;
    const entry = tasks.get(task) ?? {
      task,
      title: taskTitles[task],
      files: [],
      lines: 0,
    };
    entry.files.push(task === "images" ? change.path : name);
    const current =
      task === "database" || task === "dialogue" ? left(name, task) : undefined;
    entry.lines += current ?? lines.get(change.path) ?? 0;
    tasks.set(task, entry);
  }
  return (["database", "dialogue", "plugins", "images"] as const).flatMap(
    (task) => tasks.get(task) ?? [],
  );
}
