import { useState } from "react";
import { VirtualList } from "../../ui/VirtualList";
import { displayText } from "../../ui/displayText";
import { Button } from "../../ui/Button";
import { Modal } from "../../ui/Modal";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { LineChange, type LineChangeRow } from "../../ui/LineChange";
import {
  textChanges,
  textSummary,
  type FileText,
  type TextLine,
} from "./versionState";

const paths = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
const rows = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value)
    ? value.filter((item) => item && typeof item === "object")
    : [];
const rowKey = (row: Record<string, unknown>) => String(row.path);

export function VersionChanges({
  value,
  listLabel = "Files affected by the official update",
  unread = "Review this file after updating.",
}: {
  value: Record<string, unknown>;
  /** Names the file list for assistive technology. */
  listLabel?: string;
  /** A file's result when the comparison names none. */
  unread?: string;
}) {
  const [query, setQuery] = useState("");
  const [opened, setOpened] = useState<FileText | null>(null);
  const changes = [
    ...rows(value.file_changes),
    ...rows(value.external_changes),
  ];
  const filtered = changes.filter((row) =>
    String(row.path).toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  const text = textChanges(value);
  const texts = new Map(text?.files.map((file) => [file.path, file]));
  const overlap = paths(value.overlapping_paths);
  const warnings = [
    ...paths(value.json_warnings),
    ...rows(value.image_changes)
      .filter((row) => row.warning === true)
      .map((row) => `${displayText(row.path)}: ${displayText(row.result)}`),
  ];
  return (
    <div className="version-changes">
      {text
        ? !!(text.to_translate || text.replaced || text.edited) && (
            <p className="version-text-summary">{textSummary(text)}</p>
          )
        : !!overlap.length && (
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
              label={listLabel}
              empty={<p>No matching files.</p>}
            >
              {(row) => {
                const file = texts.get(String(row.path));
                // A file's counts add nothing when they are the whole update's.
                const summary =
                  file && text && textSummary(file) !== textSummary(text)
                    ? textSummary(file)
                    : undefined;
                return (
                  <div className="version-file">
                    {file?.lines.length ? (
                      <Button variant="link" onClick={() => setOpened(file)}>
                        {String(row.path)}
                      </Button>
                    ) : (
                      <strong>{String(row.path)}</strong>
                    )}
                    <span className="version-file-result">
                      {[displayText(row.result) || unread, summary]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <span className="version-file-change">
                      {String(row.change)}
                    </span>
                  </div>
                );
              }}
            </VirtualList>
          </div>
        </>
      )}
      {opened && <FileLines file={opened} close={() => setOpened(null)} />}
    </div>
  );
}

const kinds: Record<TextLine["kind"], string> = {
  added: "New",
  changed: "Changed",
  removed: "Removed",
  replaced: "Translation replaced",
  edited: "Changed",
};
/** A checkpoint's line reads Added or Removed when it has one side only. */
const kindLabel = (line: TextLine) =>
  line.kind !== "edited"
    ? kinds[line.kind]
    : line.before === null
      ? "Added"
      : line.after === null
        ? "Removed"
        : kinds.edited;

/** A line's versions: the old release's, the new one's and its translation. */
function lineRows(line: TextLine): LineChangeRow[] {
  const japanese = (
    label: string,
    text: string | null,
    change?: "added" | "removed",
  ) => (text === null ? [] : [{ label, text, change, lang: "ja" }]);
  // The update drops every translation it lists; the line goes back to Japanese.
  const translation =
    line.translation === null
      ? []
      : [
          {
            label: "Translation",
            text: line.translation,
            change: "removed" as const,
          },
        ];
  switch (line.kind) {
    case "edited":
      return [
        ...(line.before === null
          ? []
          : [
              {
                label: "Before",
                text: line.before,
                change: "removed" as const,
              },
            ]),
        ...(line.after === null
          ? []
          : [{ label: "After", text: line.after, change: "added" as const }]),
      ];
    case "added":
      return japanese("Japanese", line.after, "added");
    case "removed":
      return [...japanese("Was", line.before, "removed"), ...translation];
    case "replaced":
      return [
        ...japanese("Japanese", line.after ?? line.before),
        ...translation,
      ];
    case "changed":
      return [
        ...japanese("Was", line.before, "removed"),
        ...japanese("Now", line.after, "added"),
        ...translation,
      ];
  }
}

/** One file's changed lines, as the update leaves them in the game. */
function FileLines({ file, close }: { file: FileText; close: () => void }) {
  return (
    <Modal label={file.path} size="lg" onDismiss={close}>
      <DialogHeader
        title={file.path}
        description={textSummary(file)}
        onClose={close}
      />
      <DialogBody>
        <ol className="version-lines">
          {file.lines.map((line, index) => (
            <li key={index}>
              <strong>{kindLabel(line)}</strong>
              <LineChange rows={lineRows(line)} />
            </li>
          ))}
        </ol>
        {!!file.more && (
          <p className="muted">
            And {file.more.toLocaleString()} more{" "}
            {file.more === 1 ? "line" : "lines"}.
          </p>
        )}
      </DialogBody>
    </Modal>
  );
}
