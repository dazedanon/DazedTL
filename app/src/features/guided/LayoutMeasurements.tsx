import type { ContextSetup, GuidedOptions } from "../../api/contracts";

export function LayoutMeasurements({ setup, current }: { setup: ContextSetup; current: GuidedOptions["widths"] }) {
  if (!setup.layout) return null;
  const { widths, reason, evidence } = setup.layout;
  const labels: Record<keyof typeof widths, string> = { width: "Dialogue", faceWidth: "With portrait", listWidth: "List / help", noteWidth: "Notes" };
  return <div className="context-measurements">
    <p className="context-measurement-caption">Measured character limits <span className="badge">{setup.layoutApplication === "applied" ? "Saved" : setup.layoutApplication === "pending" ? "Pending save" : setup.layoutApplication === "manual" ? "Manually adjusted" : "Investigation"}</span></p>
    <dl className="context-measurement-values">{(Object.keys(labels) as (keyof typeof widths)[]).map(key => <div key={key}>
      <dt>{labels[key]}</dt><dd>{widths[key]}</dd>{current[key] !== widths[key] && <small>Current: {current[key]}</small>}
    </div>)}</dl>
    {setup.layoutMessage && <p className="field-error">{setup.layoutMessage}</p>}
    <details className="context-report-details"><summary>Investigation notes</summary><p>{reason}</p></details>
    {!!evidence.length && <details className="context-report-details"><summary>Sources ({evidence.length})</summary><ul>{evidence.map((ref, index) => <li key={index}><span className="path">{ref.file}</span> — {ref.location}</li>)}</ul></details>}
  </div>;
}
