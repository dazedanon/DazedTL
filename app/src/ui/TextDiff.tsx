/**
 * A unified diff shown as text changes: removed and added lines are tinted,
 * each hunk starts with its line number, and file headers are left out.
 */
export function TextDiff({ diff, label }: { diff: string; label: string }) {
  const lines = diff.split("\n").filter(
    // The file headers name the two sides, which the review already says.
    (line) => !line.startsWith("--- ") && !line.startsWith("+++ "),
  );
  return (
    <div className="text-diff" role="group" aria-label={label}>
      {lines.map((line, index) => {
        const hunk = /^@@ -\d+(?:,\d+)? \+(\d+)/.exec(line);
        if (hunk)
          return (
            <div key={index} className="text-diff-hunk">
              Line {Number(hunk[1]).toLocaleString()}
            </div>
          );
        const kind = line.startsWith("-")
          ? "removed"
          : line.startsWith("+")
            ? "added"
            : "context";
        return (
          <div key={index} className="text-diff-line" data-kind={kind}>
            <span className="text-diff-mark" aria-hidden="true">
              {kind === "removed" ? "−" : kind === "added" ? "+" : ""}
            </span>
            {kind !== "context" && (
              <span className="sr-only">
                {kind === "removed" ? "Removed: " : "Added: "}
              </span>
            )}
            {line.slice(1)}
          </div>
        );
      })}
    </div>
  );
}
