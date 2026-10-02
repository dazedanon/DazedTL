import type { EngineValue, SpeakerSetup } from "../../api/contracts";

export function SpeakerFindings({ findings, values }: { findings: SpeakerSetup; values: Record<string, EngineValue> }) {
  return <div className="guided-speaker-findings">
    <p className="muted">Automatic setup enables only high-confidence rules with source evidence. Manual overrides are marked.</p>
    {findings.rules.map((rule) => <section key={rule.key}>
      <div className="section-heading"><h3>{rule.label}</h3><span className="badge">{findings.overrides.includes(rule.key) ? "Manual · " : ""}{values[rule.key] === true ? "On" : "Off"}</span></div>
      <p>{rule.reason}</p>
      <details><summary>{rule.confidence === "high" ? "High confidence" : "Needs more evidence"} · {rule.evidence.length} source {rule.evidence.length === 1 ? "reference" : "references"}</summary>
        <ul>{rule.evidence.map((ref, index) => <li key={index}><span className="path">{ref.file}</span> — {ref.location}</li>)}</ul>
      </details>
    </section>)}
  </div>;
}
