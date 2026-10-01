import type { RequestPreview } from "../../api/contracts";

const kinds = {
  dialogue: "Dialogue",
  narration: "Narration",
  ui: "UI text",
  unknown: "Unclassified text",
};

export function RequestLines({ preview }: { preview: RequestPreview }) {
  const context = preview.request.context;
  return (
    <div className="translation-table-wrap">
      <table className="translation-table">
        <thead>
          <tr>
            <th>Source</th>
            <th>Saved translation</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(preview.request.sources).map(([id, source]) => {
            const kind = context.line_kinds?.[id];
            const speaker = context.speakers?.[id];
            const note = context.qa_notes?.[id];
            return (
              <tr key={id}>
                <td>
                  <small>{id}</small>
                  <div className="translation-line-context">
                    {kind ? kinds[kind] : "Text type not recorded"}
                    {speaker
                      ? " · " + speaker
                      : kind === "dialogue" || kind === "unknown"
                        ? " · Speaker unknown"
                        : !kind && speaker === null
                          ? " · Speaker unknown or not applicable"
                          : ""}
                  </div>
                  <p>{source}</p>
                </td>
                <td>
                  {preview.result?.translations[id] || "Pending"}
                  {note && (
                    <div className="translation-review-note">
                      <strong>
                        {preview.result?.reviewed?.[id]
                          ? "Source review recorded"
                          : "Needs source review"}
                      </strong>
                      <p>{note}</p>
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
