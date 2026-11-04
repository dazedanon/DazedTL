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

/** A line's text as an earlier run had it changed into this one: removed
 * words struck through where they stood, added ones marked. */
function Changed({ before, after }: { before: string; after: string }) {
  const edits = useMemo(() => wordEdits(before, after), [before, after]);
  // A line rewritten whole reads as its old version over its new one.
  const whole =
    edits.length === 2 &&
    edits[0].kind === "removed" &&
    edits[1].kind === "added";
  return edits.map((edit, index) => {
    if (edit.kind === "same") return edit.text;
    // Spaces at a change's edges stay outside its mark.
    const [, lead, text, trail] = /^(\s*)(.*?)(\s*)$/su.exec(edit.text)!;
    const Mark = edit.kind === "added" ? "ins" : "del";
    return (
      <Fragment key={index}>
        {lead}
        <Mark>{text}</Mark>
        {whole && index === 0 ? "\n" : trail}
      </Fragment>
    );
  });
}

/**
 * The comparison's lines: the source with its speaker, then each model's
 * translation, with what the checks found under it. Picking marks one
 * translation per line as the best; Tune settings marks what changed since
 * an earlier run instead.
 */
export function CompareGrid({
  comparison,
  columns,
  empty,
  marks,
  pick,
  before,
  label,
}: {
  comparison: Comparison | undefined;
  columns: readonly CompareColumn[];
  /** Says why there are no lines yet. */
  empty: ReactNode;
  marks?: Record<string, number>;
  /** Marks a translation as its line's best, or clears the mark. */
  pick?: (row: CompareRow, model: number | null) => void;
  /** Each line's text in the run Tune settings compares with. */
  before?: (row: CompareRow) => string | undefined;
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
                const earlier = translation && before?.(row);
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
                      {earlier !== undefined && earlier !== null ? (
                        <Changed before={earlier} after={translation.text} />
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
