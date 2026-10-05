import type { ContextSetup } from "../../api/contracts";

export function LayoutMeasurements({
  layout,
}: {
  layout: ContextSetup["layout"];
}) {
  if (!layout) return null;
  const { reason, evidence } = layout;
  return (
    <details className="context-measurements">
      <summary>Measurement details</summary>
      <p>{reason}</p>
      {!!evidence.length && (
        <details className="context-report-details">
          <summary>Sources ({evidence.length})</summary>
          <ul>
            {evidence.map((ref, index) => (
              <li key={index}>
                <span className="path">{ref.file}</span> — {ref.location}
              </li>
            ))}
          </ul>
        </details>
      )}
    </details>
  );
}
