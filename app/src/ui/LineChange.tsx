import { Fragment, useMemo } from "react";
import { changedWords, type WordRun } from "./changedWords";

export type LineChangeRow = {
  label: string;
  text: string;
  /** The side of a change the row shows, tinted to match. */
  change?: "added" | "removed";
  lang?: string;
  /** Spans of the text to mark, such as the terms a check names. */
  marks?: readonly { start: number; end: number }[];
};

/** The text in runs, each marked when a span covers it. */
function markedRuns(text: string, marks: LineChangeRow["marks"] = []) {
  const runs: WordRun[] = [];
  let position = 0;
  for (const { start, end } of [...marks].sort((a, b) => a.start - b.start)) {
    if (start < position) continue;
    if (start > position)
      runs.push({ text: text.slice(position, start), changed: false });
    runs.push({ text: text.slice(start, end), changed: true });
    position = end;
  }
  if (position < text.length)
    runs.push({ text: text.slice(position), changed: false });
  return runs;
}

/**
 * A line and the other versions of it, each labelled in a column. When the
 * line was both removed and added, the words that changed between the two
 * are marked; a row may also mark spans of its own, such as a term.
 */
export function LineChange({ rows }: { rows: readonly LineChangeRow[] }) {
  const removed = rows.find((row) => row.change === "removed");
  const added = rows.find((row) => row.change === "added");
  // Keyed on the texts, since callers build their rows afresh each render.
  const before = removed?.text;
  const after = added?.text;
  const words = useMemo(
    () =>
      before !== undefined && after !== undefined
        ? changedWords(before, after)
        : undefined,
    [before, after],
  );
  const marked = (row: LineChangeRow): WordRun[] | undefined =>
    !words
      ? undefined
      : row === added
        ? words.after
        : row === removed
          ? words.before
          : undefined;
  return (
    <dl className="line-change">
      {rows.map((row, index) => {
        const diff = marked(row);
        const runs =
          diff || (row.marks?.length ? markedRuns(row.text, row.marks) : null);
        const Mark = !diff ? "mark" : row.change === "added" ? "ins" : "del";
        return (
          <Fragment key={index}>
            <dt data-change={row.change}>{row.label}</dt>
            <dd data-change={row.change} lang={row.lang}>
              {runs
                ? runs.map((run, part) => (
                    <Fragment key={part}>
                      {run.changed ? <Mark>{run.text}</Mark> : run.text}
                    </Fragment>
                  ))
                : row.text}
            </dd>
          </Fragment>
        );
      })}
    </dl>
  );
}
