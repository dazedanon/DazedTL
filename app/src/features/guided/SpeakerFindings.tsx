import type { EngineValue, SpeakerSetup } from "../../api/contracts";
import { speakerOptions } from "./speakerOptions";

export function SpeakerFindings({ findings, values }: { findings: SpeakerSetup; values: Record<string, EngineValue> }) {
  return <div className="guided-speaker-findings">
    {findings.rules.map((rule) => <details className="context-finding" key={rule.key}>
      <summary><span className="context-finding-summary"><span className="context-finding-title"><strong>{speakerOptions[rule.key]?.label || rule.label}</strong>
        <span className={`badge context-rule-state ${values[rule.key] === true ? "enabled" : "disabled"}`}>{values[rule.key] === true ? "On" : "Off"}</span>
        {findings.overrides.includes(rule.key) && <span className="badge context-rule-manual">Manual</span>}</span>
        <span className="context-finding-meta">{rule.confidence[0].toUpperCase() + rule.confidence.slice(1)} confidence · {rule.evidence.length} {rule.evidence.length === 1 ? "source" : "sources"}</span></span></summary>
      <div className="context-finding-details"><p>{rule.reason}</p>
        {!!rule.evidence.length && <ul>{rule.evidence.map((ref, index) => <li key={index}><span className="path">{ref.file}</span> — {ref.location}</li>)}</ul>}
      </div>
    </details>)}
  </div>;
}
