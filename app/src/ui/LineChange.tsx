import { Fragment, useMemo } from "react";
import { changedWords, type WordRun } from "./changedWords";

export type LineChangeRow = {
  label: string;
  text: string;
  /** The side of a change the row shows, tinted to match. */
  change?: "added" | "removed";
  lang?: string;
};

/**
 * A line and the other versions of it, each labelled in a column. When the
 * line was both removed and added, the words that changed between the two
 * are marked.
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
        const runs = marked(row);
        const Mark = row.change === "added" ? "ins" : "del";
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
