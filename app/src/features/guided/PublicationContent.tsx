import type { Preview } from "../../api/contracts";
import { PathText } from "../../ui/PathText";
import { TextDiff } from "../../ui/TextDiff";
import { VirtualList } from "../../ui/VirtualList";
import { textLocation } from "./textLocation";
import { fileCount, pathKey } from "./workspace/model";

/** The Guided actions that write reviewed text into the game. */
export const publicationActions = [
  "export_selected",
  "rewrap_apply",
  "qa_apply",
  "runtime_restore",
];

/**
 * What a text publication will change: the files an Apply overwrites, the
 * lines a rewrap changes, or the file diffs of QA fixes and restores. The
 * Apply review and the pending changes review share it.
 */
export function PublicationContent({ preview }: { preview: Preview }) {
  const applying = preview.rewrap
    ? preview.rewrap.changes_found - preview.rewrap.overflow_skipped
    : 0;
  return (
    <>
      <p className="path">
        <PathText path={preview.destination} wrap />
      </p>
      {preview.action === "export_selected" && (
        <>
          <p>
            Fully overwrite these game files with the selected saved
            translations. Existing game edits will be replaced. Working copies
            and saved runs are retained.
          </p>
          {!!preview.options.run_id && (
            <p>
              Uses the saved files from this run. Reapplying makes no API
              requests.
            </p>
          )}
          {!!preview.paths.length && (
            <>
              <p>{fileCount(preview.files || preview.paths.length)}</p>
              {preview.paths.length <= 8 ? (
                <ul
                  className="guided-preview-paths"
                  aria-label="Files in this action"
                >
                  {preview.paths.map((name) => (
                    <li key={name} className="guided-preview-path">
                      {name}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="guided-preview-files">
                  <VirtualList
                    items={preview.paths}
                    itemKey={pathKey}
                    label="Files in this action"
                    empty={null}
                  >
                    {(name) => (
                      <div className="guided-preview-path">{name}</div>
                    )}
                  </VirtualList>
                </div>
              )}
            </>
          )}
        </>
      )}
      {preview.action === "runtime_restore" && (
        <p>
          Return these files to how they were before this change. Open a file
          below to compare its current and restored text. Later edits to these
          files block the restore.
        </p>
      )}
      {preview.publication && preview.action !== "export_selected" && (
        <>
          {preview.action !== "runtime_restore" && (
            <p>
              Each file is checked again first, and a backup is saved so you can
              restore it later.
            </p>
          )}
          {/* Fitting lists each change below; the file diff repeats it. */}
          {!preview.rewrap &&
            preview.publication.map((row) => (
              <details className="text-publication" key={row.path}>
                {/* The text comparison is what the user reviews; the frozen
                    plan keeps the hashes it checks. */}
                <summary>
                  {row.path}
                  {row.later_edits ? " · Replaces later game edits" : ""}
                </summary>
                <strong>
                  Changes
                  {row.truncated ? " (first 16,000 characters)" : ""}
                </strong>
                {row.diff ? (
                  <TextDiff diff={row.diff} label={`Changes to ${row.path}`} />
                ) : (
                  <p>The game file already matches.</p>
                )}
                <details>
                  <summary>Full file text</summary>
                  <strong>Current (first 16,000 characters)</strong>
                  <pre>{row.before_text}</pre>
                  <strong>After (first 16,000 characters)</strong>
                  <pre>{row.after_text}</pre>
                </details>
              </details>
            ))}
        </>
      )}
      {preview.rewrap && (
        <>
          {/* Protected overflows are found but not written, so the review
              counts and lists only the changes this apply makes. */}
          <p>
            {applying} {applying === 1 ? "change" : "changes"}
            {!!preview.rewrap.overflow_skipped &&
              ` · ${preview.rewrap.overflow_skipped} protected ${preview.rewrap.overflow_skipped === 1 ? "overflow" : "overflows"} skipped`}
          </p>
          {preview.rewrap.previews
            .filter(
              (row) => !(row.overflow && preview.rewrap!.overflow_skipped),
            )
            .map((row, index) => (
              <details key={index}>
                <summary>
                  {row.file_name} · {textLocation(row.locator)}
                </summary>
                <strong>Before</strong>
                <pre>{row.before}</pre>
                <strong>After</strong>
                <pre>{row.after}</pre>
              </details>
            ))}
        </>
      )}
    </>
  );
}
