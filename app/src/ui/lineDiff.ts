import {
  commonSubsequence,
  comparisonLimit,
  type Edit,
} from "./changedWords.ts";

/** Unchanged lines a hunk shows around its changes, as `diff -u` does. */
const context = 3;

/**
 * The unified diff that turns `before` into `after`, line by line, as
 * TextDiff shows one: its hunks only, without file headers. A rewrite
 * longer than the comparison weighs is one change.
 */
export function lineDiff(before: string, after: string) {
  const left = before.split("\n");
  const right = after.split("\n");
  let start = 0;
  while (
    start < left.length &&
    start < right.length &&
    left[start] === right[start]
  )
    start++;
  let end = 0;
  while (
    end < left.length - start &&
    end < right.length - start &&
    left[left.length - 1 - end] === right[right.length - 1 - end]
  )
    end++;
  const removed = left.slice(start, left.length - end);
  const added = right.slice(start, right.length - end);
  const same = (lines: string[]): Edit[] =>
    lines.map((text) => ({ kind: "same", text }));
  const edits: Edit[] = [
    ...same(left.slice(0, start)),
    ...(removed.length * added.length > comparisonLimit
      ? [
          ...removed.map((text): Edit => ({ kind: "removed", text })),
          ...added.map((text): Edit => ({ kind: "added", text })),
        ]
      : commonSubsequence(removed, added)),
    ...same(left.slice(left.length - end)),
  ];
  return hunks(edits).join("\n");
}

/** The edits grouped into hunks of changes with their context lines. */
function hunks(edits: Edit[]) {
  const changed = edits.flatMap((edit, index) =>
    edit.kind === "same" ? [] : [index],
  );
  const result: string[] = [];
  let at = 0;
  while (at < changed.length) {
    const first = Math.max(0, changed[at] - context);
    let last = changed[at];
    while (at + 1 < changed.length && changed[at + 1] - last <= 2 * context)
      last = changed[++at];
    at++;
    const stop = Math.min(edits.length, last + context + 1);
    const before = edits.slice(0, first);
    const old = before.filter((edit) => edit.kind !== "added").length + 1;
    const now = before.filter((edit) => edit.kind !== "removed").length + 1;
    const lines = edits.slice(first, stop);
    const count = (kind: Edit["kind"]) =>
      lines.filter((edit) => edit.kind !== kind).length;
    result.push(`@@ -${old},${count("added")} +${now},${count("removed")} @@`);
    for (const edit of lines)
      result.push(
        (edit.kind === "removed" ? "-" : edit.kind === "added" ? "+" : " ") +
          edit.text,
      );
  }
  return result;
}
