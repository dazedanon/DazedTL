import { useState } from "react";
import type { Phase, Preview, PublicationChange } from "../../api/contracts";
import { Notice } from "../../ui/Notice";
import { PathText } from "../../ui/PathText";
import { TextDiff } from "../../ui/TextDiff";
import { VirtualList } from "../../ui/VirtualList";
import { fileCount, pathKey, phaseLabels } from "./workspace/model";

/** The Guided actions that write reviewed text into the game. */
export const publicationActions = [
  "export_selected",
  "qa_apply",
  "runtime_restore",
];

/**
 * What a text publication will change: the files an Apply overwrites, or
 * the file diffs of QA fixes and restores.
 */
export function PublicationContent({
  preview,
  phase,
}: {
  preview: Preview;
  phase?: Phase;
}) {
  const fileName = (path: string) => path.split("/").pop();
  // Files changed in the game since their last Apply, such as hand fixes,
  // which a full overwrite replaces.
  const edited = (preview.publication || [])
    .filter((row) => row.later_edits)
    .map((row) => fileName(row.path));
  // Files whose newest copy another task's run saved, such as Other event
  // text's output over Maps & events', which this Apply puts in too.
  const carried = new Map<Phase, string[]>();
  for (const row of preview.publication || [])
    if (row.task && row.task !== phase)
      carried.set(row.task, [
        ...(carried.get(row.task) || []),
        fileName(row.path) || row.path,
      ]);
  return (
    <>
      <p className="path">
        <PathText path={preview.destination} wrap />
      </p>
      {preview.action === "export_selected" && (
        <>
          <p>
            Fully overwrite these game files with the selected saved
            translations, wrapping any line too wide for the Line widths.
            Existing game edits will be replaced. Working copies and saved runs
            are retained.
          </p>
          {!!preview.options.run_id && (
            <p>
              Uses the saved files from this run. Reapplying makes no API
              requests.
            </p>
          )}
          {[...carried].map(([task, files]) => (
            <p key={task}>
              Also applies {phaseLabels[task]}&apos;s saved translations in{" "}
              {files.slice(0, 3).join(", ")}
              {files.length > 3 && ` and ${files.length - 3} more`}.
            </p>
          ))}
          {!!edited.length && (
            <Notice tone="warning">
              {edited.slice(0, 3).join(", ")}
              {edited.length > 3 && ` and ${edited.length - 3} more`}
              {edited.length === 1 ? " was" : " were"} edited in the game after
              the last Apply. Applying replaces those edits.
            </Notice>
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
              Each file is checked again first, and the change is saved as a
              checkpoint you can undo.
            </p>
          )}
          {preview.publication.map((row) => (
            <PublicationFile key={row.path} row={row} />
          ))}
        </>
      )}
    </>
  );
}

/**
 * One file's text comparison, rendered once opened: a large batch's closed
 * rows held hundreds of thousands of diff lines.
 */
function PublicationFile({ row }: { row: PublicationChange }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="text-publication"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      {/* The text comparison is what the user reviews; the frozen plan
          keeps the hashes it checks. */}
      <summary>{row.path}</summary>
      {open && (
        <>
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
        </>
      )}
    </details>
  );
}
