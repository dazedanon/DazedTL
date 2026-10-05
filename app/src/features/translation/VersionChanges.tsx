import { useState } from "react";
import { VirtualList } from "../../ui/VirtualList";
import { updateCounts } from "./versionState";

const paths = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
const rows = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value)
    ? value.filter((item) => item && typeof item === "object")
    : [];
const rowKey = (row: Record<string, unknown>) => String(row.path);

export function VersionChanges({ value }: { value: Record<string, unknown> }) {
  const [query, setQuery] = useState("");
  const changes = [
    ...rows(value.file_changes),
    ...rows(value.external_changes),
  ];
  const filtered = changes.filter((row) =>
    String(row.path).toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  const overlap = paths(value.overlapping_paths);
  const counts = updateCounts(value);
  const warnings = [
    ...paths(value.json_warnings),
    ...rows(value.image_changes)
      .filter((row) => row.warning === true)
      .map((row) => `${row.path}: ${row.result}`),
  ];
  return (
    <div className="version-changes">
      <dl className="version-counts">
        {[
          ["Added", counts.added],
          ["Changed", counts.changed],
          ["Removed", counts.removed],
        ].map(([label, count]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{count}</dd>
          </div>
        ))}
      </dl>
      {!!overlap.length && (
        <p>
          {overlap.length} changed{" "}
          {overlap.length === 1 ? "file also has" : "files also have"}{" "}
          translation edits. Check their expected results below.
        </p>
      )}
      {warnings.map((warning, index) => (
        <p className="banner" key={index}>
          {warning}
        </p>
      ))}
      {!!changes.length && (
        <>
          <label className="version-search">
            Find a changed file
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filename or path"
            />
          </label>
          <div className="version-file-list">
            <VirtualList
              items={filtered}
              itemKey={rowKey}
              label="Files affected by the official update"
              empty={<p>No matching files.</p>}
            >
              {(row) => (
                <div className="version-file">
                  <div>
                    <strong>{String(row.path)}</strong>
                    <span>{String(row.change)}</span>
                  </div>
                  <p>
                    {String(row.result || "Review this file after updating.")}
                  </p>
                </div>
              )}
            </VirtualList>
          </div>
        </>
      )}
      <details>
        <summary>Full comparison details</summary>
        <pre className="translation-json">{JSON.stringify(value, null, 2)}</pre>
      </details>
    </div>
  );
}
