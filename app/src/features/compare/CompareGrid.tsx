import { useMemo, type ReactNode } from "react";
import { Check } from "lucide-react";
import type { CompareRow, Comparison } from "../../api/contracts";
import { useLanguages } from "../../app/LanguagesProvider";
import { changesAgainst } from "../../ui/changedWords";
import { StatusIcon } from "../../ui/StatusIcon";
import { hiddenNotes, lineOrder } from "./compareView";

/** What a header over translations says. */
type Header = {
  title: ReactNode;
  /** Controls at the end of the title's row, such as the column's menu. */
  actions?: ReactNode;
  /** A mark after the title, such as Most picked. */
  badge?: ReactNode;
  /** A muted line under the title, such as the connection and settings. */
  subtitle?: ReactNode;
  /** A muted line under that, such as the price. */
  detail?: ReactNode;
  /** Why a model has no lines, as failed. */
  error?: string;
  /** Why a model was left out before anything was sent, as a warning that
   * names the fix. */
  warning?: string;
};

/** A model's column, in the order the grid shows them. */
export type CompareColumn = Header & {
  /** The model's place in the comparison's candidates and rows. */
  position: number;
};

/** A note under a model or a line: a model that failed, or what the checks
 * found, after its status mark. */
export function CompareFlag({
  status,
  children,
}: {
  status: "failed" | "warning";
  children: ReactNode;
}) {
  return (
    <span className="compare-flag" data-status={status}>
      <StatusIcon status={status} size={13} />
      <span>{children}</span>
    </span>
  );
}

function Changed({ text, other }: { text: string; other: string }) {
  const runs = useMemo(() => changesAgainst(other, text), [other, text]);
  return runs.map((run, index) =>
    run.removed ? (
      <span
        key={index}
        className="compare-removed"
        role="img"
        aria-label={`Removed: ${run.removed}`}
        title={`Removed: ${run.removed}`}
      />
    ) : run.changed ? (
      <ins key={index}>{run.text}</ins>
    ) : (
      run.text
    ),
  );
}

/** A header's title row, then its lines and notes under it. */
function HeaderContent({ header }: { header: Header }) {
  return (
    <>
      <div className="compare-grid-title">
        <strong>
          {header.title}
          {header.badge}
        </strong>
        {header.actions}
      </div>
      {header.subtitle && (
        <span className="compare-grid-detail">{header.subtitle}</span>
      )}
      {header.detail && (
        <span className="compare-grid-detail">{header.detail}</span>
      )}
      {header.error && (
        <CompareFlag status="failed">{header.error}</CompareFlag>
      )}
      {header.warning && (
        <CompareFlag status="warning">{header.warning}</CompareFlag>
      )}
    </>
  );
}

/**
 * The comparison's lines: the source with its speaker, then each model's
 * translation, with what the checks found under it. Picking marks one
 * translation per line as the best; Mark differences marks the words each
 * translation changed from the first on its line.
 *
 * While names are hidden, one header spans the translations, saying what
 * it can of models without lines without telling which, and each line
 * shows its translations in its own order, so no side belongs to a model.
 */
export function CompareGrid({
  comparison,
  columns,
  hidden = false,
  add,
  empty,
  marks,
  pick,
  differences = false,
  label,
}: {
  comparison: Comparison | undefined;
  /** Each model's column, in the order they show, while names show. */
  columns: readonly CompareColumn[];
  /** Whether names are hidden: one header then spans the translations in
   * place of the columns'. */
  hidden?: boolean;
  /** The header of the place the next column goes, such as Add model. */
  add?: ReactNode;
  /** Says why there are no lines yet. */
  empty: ReactNode;
  marks?: Record<string, number>;
  /** Marks a translation as its line's best, or clears the mark. */
  pick?: (row: CompareRow, model: number | null) => void;
  /** Whether Mark differences is on. */
  differences?: boolean;
  label: string;
}) {
  const languages = useLanguages();
  const blind = hidden && comparison ? comparison : null;
  const rows = comparison?.rows ?? [];
  const count = blind ? blind.candidates.length : columns.length;
  const positions = columns.map((column) => column.position);
  return (
    <table
      className="compare-grid"
      data-columns={count}
      data-add={add ? "" : undefined}
      aria-label={label}
    >
      <colgroup>
        <col className="compare-grid-source" />
        {Array.from({ length: count }, (_, place) => (
          <col key={place} />
        ))}
        {add && <col className="compare-grid-add" />}
      </colgroup>
      <thead>
        <tr>
          <th scope="col">
            <strong>{languages.source}</strong>
          </th>
          {blind ? (
            <th scope="col" colSpan={count}>
              <HeaderContent
                header={{
                  title: languages.target,
                  subtitle: "In a new order on every line",
                  ...hiddenNotes(blind),
                }}
              />
            </th>
          ) : (
            columns.map((column) => (
              <th scope="col" key={column.position}>
                <HeaderContent header={column} />
              </th>
            ))
          )}
          {add && <th scope="col">{add}</th>}
        </tr>
      </thead>
      <tbody>
        {!rows.length ? (
          <tr>
            <td className="compare-grid-empty" colSpan={count + (add ? 2 : 1)}>
              {empty}
            </td>
          </tr>
        ) : (
          rows.map((row) => {
            // The models' places in the line's cells, left to right.
            const places = blind ? lineOrder(blind, row) : positions;
            // Mark differences marks each against the first shown.
            const first = places.find((place) => row.translations[place]);
            const other =
              differences && first !== undefined
                ? row.translations[first]
                : null;
            return (
              <tr key={row.id}>
                <th scope="row" lang={languages.sourceTag ?? undefined}>
                  <span className="compare-speaker">{row.speaker}</span>
                  <span className="compare-text">{row.source}</span>
                </th>
                {places.map((position) => {
                  const model =
                    comparison!.candidates[position]?.index ?? position;
                  const translation = row.translations[position];
                  const problems = row.problems[position] ?? [];
                  const best = !!marks && marks[row.id] === model;
                  const differs = position !== first && other;
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
                          <Changed
                            text={translation.text}
                            other={differs.text}
                          />
                        ) : (
                          translation.text
                        )}
                      </span>
                      {problems.map((problem) => (
                        <CompareFlag status="warning" key={problem}>
                          {problem}
                        </CompareFlag>
                      ))}
                    </>
                  );
                  return (
                    <td key={position} data-best={best || undefined}>
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
                {add && <td />}
              </tr>
            );
          })
        )}
      </tbody>
    </table>
  );
}
