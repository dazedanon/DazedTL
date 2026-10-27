import type {
  Checkpoint,
  GitStatus,
  TranslationJob,
} from "../../api/contracts.ts";
import { plural } from "../../ui/displayText.ts";

/**
 * What the Checkpoints tab reads its timeline for: the project and the
 * translation branch's head, so it reads when the tab opens and again after a
 * write moves the branch, never for a poll that changed nothing in Git.
 * Edits made outside DazedTL show from those reads.
 */
export function readKey(projectId: string, git: GitStatus | null | undefined) {
  return git?.configured ? `${projectId}\n${git.translation_commit}` : null;
}

/**
 * Whether a go back, undo or copy reports beside `row`: a finished go back
 * or undo that changed files beside the checkpoint it made, its result's
 * commit, which stays where it is when later checkpoints come; anything
 * else, such as one that found nothing to change and made none, beside the
 * row it was started from.
 */
export function reportsBeside(
  job: Pick<TranslationJob, "status" | "action" | "target" | "result">,
  row: Checkpoint,
) {
  const made = job.result as { files?: number; commit?: unknown } | null;
  if (
    job.status === "complete" &&
    job.action !== "checkpoint_copy" &&
    made?.files
  )
    return made.commit === row.commit;
  return job.target === row.commit;
}

export const when = (time: string) =>
  new Date(time).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
export const day = (time: string) =>
  new Date(time).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
export const fileName = (path: string) => path.split("/").pop() || path;

/** The files a checkpoint changed, as selectionNames words a selection. */
export function changedFiles(row: Checkpoint) {
  const names = row.names.map(fileName);
  if (row.kind === "setup") return plural(row.files, "file");
  if (row.kind === "update")
    return `${row.release === "patch" ? "Patch · " : ""}${plural(row.files, "file")} changed`;
  return row.files > 3
    ? `${plural(row.files, "file")}: ${names.slice(0, 2).join(", ")} and ${row.files - 2} more`
    : names.join(", ");
}

export function blockedBy(row: Checkpoint) {
  const later = row.blocker!;
  const names = later.files.map(fileName);
  const shared =
    names.length > 3
      ? `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`
      : names.length > 1
        ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`
        : names[0];
  // Edits made outside DazedTL become a checkpoint only with its next change.
  if (!later.commit)
    return `${shared} ${later.files.length === 1 ? "was" : "were"} edited outside DazedTL since; go back to before this change instead.`;
  return `Undo the later ${quoted(later.title)} first; it also changed ${shared}.`;
}

/** Consecutive checkpoints of one stage, so the list reads by stage. */
export function runs(rows: Checkpoint[]) {
  const grouped: { group: string; rows: Checkpoint[] }[] = [];
  for (const row of rows) {
    const last = grouped.at(-1);
    if (last?.group === row.group) last.rows.push(row);
    else grouped.push({ group: row.group, rows: [row] });
  }
  return grouped;
}

/** A title in quotes, single ones inside a title already quoting another,
 * as checkpoint names quote theirs. */
export const quoted = (title: string) =>
  title.includes("“") ? `‘${title}’` : `“${title}”`;

/** A copy's folder name with its parenthesized version and date stamp kept
 * whole, so a narrow result wraps before the stamp, never inside it. */
export const copyName = (name: string) =>
  name.replace(/ \(.*\)$/, (stamp) =>
    stamp.replaceAll(" ", "\u00a0").replaceAll("-", "\u2011"),
  );
