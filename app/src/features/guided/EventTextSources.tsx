import type { EngineValue, EventTextState } from "../../api/contracts";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { FieldRow } from "../../ui/FieldRow";
import { Message } from "../../ui/Feedback";
import { manualSources, sourceErrors, type SelectorKey } from "./eventTextSelection";

export function EventTextSources({ state, values, disabled, change, openPicker, recommendations }: {
  state: EventTextState; values: Record<string, EngineValue>; disabled: boolean;
  change: (key: string, value: EngineValue) => void; openPicker: (key: SelectorKey) => void; recommendations: () => void;
}) {
  const manual = manualSources(state, values);
  return <>
    <ActionList><ActionRow label={<><strong>Investigation findings</strong><small>{state.message}</small></>}>
      <Button disabled={disabled || state.status !== "ready"} onClick={recommendations}>Use recommendations</Button>
    </ActionRow></ActionList>
    <p className="muted">Recommendations are staged for your review. Manual choices remain available. Uncertain or mixed coverage stays off in recommendations.</p>
    {values.AUTONAMEPOPUP101 === true && <p className="muted">Saved AutoNamePopup speaker handling also processes supported actor-name changes, even with source 320 off. Review that inherited coverage with the actor context.</p>}
    <fieldset disabled={disabled} className="event-text-sources">
      {state.rows.map((row) => <section key={row.key} className="event-text-source" aria-label={row.label}>
        <label className="toggle"><input type="checkbox" checked={values[row.key] === true} onChange={(event) => change(row.key, event.target.checked)} />
          <span><strong>{row.label}</strong><small className="event-text-decision">{manual.includes(row.key) ? "Manual choice - requires coverage confirmation" : state.status === "ready" ? row.decision === "enable" && row.confidence === "high" && row.coverageStatus === "safe" ? "Recommended" : "Keep off / review needed" : "Not investigated"}</small></span>
        </label>
        <p className="muted">{row.reason}</p>
        {row.key === "CODE122" && <FieldRow id="event-text-variable-ids" label="Variable IDs">{(props) => <input {...props} type="text" value={String(values.CODE122_VAR_RANGES || "")} disabled={!values.CODE122} onChange={(event) => change("CODE122_VAR_RANGES", event.target.value)} placeholder="35, 37-40, 402" />}</FieldRow>}
        {row.selector && <ActionList><ActionRow label={<><strong>{row.key === "CODE357" ? "MZ plugin command filters" : "Script text filters"}</strong><small>{Array.isArray(values[row.selector]) ? (values[row.selector] as string[]).length : 0} of {row.choices.length} registered entries selected{!values[row.key] && " (source off)"}. {state.builtinHits[row.key]?.length || 0} built-in handlers detected in this scope.</small></>}>
          <Button disabled={disabled} onClick={() => openPicker(row.selector as SelectorKey)}>Edit selection</Button>
        </ActionRow></ActionList>}
        <details><summary>Coverage, exclusions & evidence</summary>
          <p>{row.coverage}</p>
          {!!row.builtins.length && <p>Built-in coverage when enabled: {row.builtins.join(", ")}. These have no individual switches.</p>}
          {!!row.observations.length && <ul>{row.observations.map((item, index) => <li key={index}>{item}</li>)}</ul>}
          {!!row.exclusions.length && <><strong>Excluded or unsupported work</strong><ul>{row.exclusions.map((item, index) => <li key={index}>{item}</li>)}</ul><p>Listed exclusions are evidence. If they share enabled handler coverage, the engine cannot isolate them; keep that coverage off or review an explicit manual override.</p></>}
          {!!row.evidence.length && <ul>{row.evidence.map((ref, index) => <li key={index}><span className="path">{ref.file}</span> - {ref.location}</li>)}</ul>}
        </details>
      </section>)}
    </fieldset>
    {sourceErrors(state, values).map((error) => <Message key={error} message={error} />)}
  </>;
}
