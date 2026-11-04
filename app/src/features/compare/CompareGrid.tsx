import { Fragment, useMemo, type ReactNode } from "react";
import { Check, TriangleAlert } from "lucide-react";
import type { CompareRow, Comparison } from "../../api/contracts";
import { useLanguages } from "../../app/LanguagesProvider";
import { wordEdits } from "../../ui/changedWords";

/** A model's column, in the order the grid shows them. */
export type CompareColumn = {
  /** The model's place in the comparison's candidates and rows. */
  position: number;
  title: ReactNode;
  /** A mark after the title, such as Most picked. */
  badge?: ReactNode;
  /** A muted line under the title, such as the price. */
  detail?: ReactNode;
  /** Why the model has no lines, in amber under its header. */
  error?: string;
};

/** How a line's text differs from another run's: on the earlier run's side
 * the words the later one dropped are marked, on the later run's side the
 * words it brought. */
export type Difference = { other: string; side: "before" | "after" };

function Changed({
  text,
  difference,
}: {
  text: string;
  difference: Difference;
}) {
  const { other, side } = difference;
  const edits = useMemo(
    () => (side === "after" ? wordEdits(other, text) : wordEdits(text, other)),
    [other, text, side],
  );
  const mine = side === "after" ? "added" : "removed";
  return edits.map((edit, index) => {
    if (edit.kind === "same") return edit.text;
    if (edit.kind !== mine) return null;
    // Spaces at a change's edges stay outside its mark.
    const [, lead, part, trail] = /^(\s*)(.*?)(\s*)$/su.exec(edit.text)!;
    const Mark = side === "after" ? "ins" : "del";
    return (
      <Fragment key={index}>
        {lead}
        <Mark>{part}</Mark>
        {trail}
      </Fragment>
    );
  });
}

/**
 * The comparison's lines: the source with its speaker, then each model's
 * translation, with what the checks found under it. Picking marks one
 * translation per line as the best; Tune settings marks what changed
 * between two runs instead.
 */
export function CompareGrid({
  comparison,
  columns,
  empty,
  marks,
  pick,
  difference,
  label,
}: {
  comparison: Comparison | undefined;
  columns: readonly CompareColumn[];
  /** Says why there are no lines yet. */
  empty: ReactNode;
  marks?: Record<string, number>;
  /** Marks a translation as its line's best, or clears the mark. */
  pick?: (row: CompareRow, model: number | null) => void;
  /** How a column's line differs from the other run's, in Tune settings. */
  difference?: (row: CompareRow, position: number) => Difference | undefined;
  label: string;
}) {
  const languages = useLanguages();
  const rows = comparison?.rows ?? [];
  return (
    <table
      className="compare-grid"
      data-columns={columns.length}
      aria-label={label}
    >
      <colgroup>
        <col className="compare-grid-source" />
        {columns.map((column) => (
          <col key={column.position} />
        ))}
      </colgroup>
      <thead>
        <tr>
          <th scope="col">
            <strong>{languages.source}</strong>
          </th>
          {columns.map((column) => (
            <th scope="col" key={column.position}>
              <strong>
                {column.title}
                {column.badge}
              </strong>
              {column.detail && (
                <span className="compare-grid-detail">{column.detail}</span>
              )}
              {column.error && (
                <span className="compare-flag">
                  <TriangleAlert size={13} aria-hidden="true" />
                  {column.error}
                </span>
              )}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {!rows.length ? (
          <tr>
            <td className="compare-grid-empty" colSpan={columns.length + 1}>
              {empty}
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr key={row.id}>
              <th scope="row" lang={languages.sourceTag ?? undefined}>
                <span className="compare-speaker">{row.speaker}</span>
                <span className="compare-text">{row.source}</span>
              </th>
              {columns.map((column) => {
                const model =
                  comparison!.candidates[column.position]?.index ??
                  column.position;
                const translation = row.translations[column.position];
                const problems = row.problems[column.position] ?? [];
                const best = !!marks && marks[row.id] === model;
                const differs =
                  translation && difference?.(row, column.position);
                const content = translation && (
                  <>
                    <span className="compare-cell-top">
                      <span className="compare-speaker">
                        {translation.speaker}
                      </span>
                      {best && (
                        <span className="compare-best">
                          <Check size={13} aria-hidden="true" />
                          Best
                        </span>
                      )}
                    </span>
                    <span
                      className="compare-text"
                      lang={languages.targetTag ?? undefined}
                    >
                      {differs ? (
                        <Changed text={translation.text} difference={differs} />
                      ) : (
                        translation.text
                      )}
                    </span>
                    {problems.map((problem) => (
                      <span className="compare-flag" key={problem}>
                        <TriangleAlert size={13} aria-hidden="true" />
                        {problem}
                      </span>
                    ))}
                  </>
                );
                return (
                  <td key={column.position} data-best={best || undefined}>
                    {pick && translation ? (
                      <button
                        type="button"
                        className="compare-pick"
                        aria-pressed={best}
                        title={best ? "Picked as best" : "Pick as best"}
                        onClick={() => pick(row, best ? null : model)}
                      >
                        {content}
                      </button>
                    ) : (
                      <div className="compare-cell">{content}</div>
                    )}
                  </td>
                );
              })}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
