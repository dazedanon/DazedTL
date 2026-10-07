import type { PluginPreview } from "../../api/contracts";

/** The plugin files an apply or restore replaces, and those it leaves. */
export function PluginApplyContent({ preview }: { preview: PluginPreview }) {
  return (
    <>
      <p>
        {preview.mode === "apply"
          ? "Replace these game files with the checked translations. Each file is checked again first, and a backup is saved for recovery."
          : "Restore these game files from their saved backups. Each file is checked again first."}
      </p>
      <div className="plugin-review-table">
        <table>
          <thead>
            <tr>
              <th>Game file</th>
              <th>Text changes</th>
            </tr>
          </thead>
          <tbody>
            {preview.files.map((file) => (
              <tr key={file.path}>
                <td>{file.destination}</td>
                <td>{file.changes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!!preview.blocked.length && (
        <details open>
          <summary>Files left unchanged</summary>
          {preview.blocked.map((file) => (
            <p key={file.path}>
              <strong>{file.path}</strong> · {file.reason}
            </p>
          ))}
        </details>
      )}
    </>
  );
}
