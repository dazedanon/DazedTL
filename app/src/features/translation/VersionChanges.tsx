import { useState } from "react";
import { VirtualList } from "../../ui/VirtualList";
import { displayText } from "../../ui/displayText";

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
  const warnings = [
    ...paths(value.json_warnings),
    ...rows(value.image_changes)
      .filter((row) => row.warning === true)
      .map((row) => `${displayText(row.path)}: ${displayText(row.result)}`),
  ];
  return (
    <div className="version-changes">
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
          <input
            className="version-search"
            aria-label="Find a changed file"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find a changed file"
          />
          <div className="version-file-list">
            <VirtualList
              items={filtered}
              itemKey={rowKey}
              label="Files affected by the official update"
              empty={<p>No matching files.</p>}
            >
              {(row) => (
                <div className="version-file">
                  <strong>{String(row.path)}</strong>
                  <span className="version-file-result">
                    {displayText(row.result) ||
                      "Review this file after updating."}
                  </span>
                  <span className="version-file-change">
                    {String(row.change)}
                  </span>
                </div>
              )}
            </VirtualList>
          </div>
        </>
      )}
    </div>
  );
}
