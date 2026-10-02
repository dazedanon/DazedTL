import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { api } from "../../api/client";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import type { EventTextState } from "../../api/contracts";
import { filteredChoices, toggleChoice, type SourcePickerDraft } from "./eventTextSelection";

export function EventTextPicker({ projectId, state, initial, save, refresh }: {
  projectId: string; state: EventTextState; initial: SourcePickerDraft; save: (value: SourcePickerDraft) => Promise<void>; refresh: () => Promise<unknown>;
}) {
  const action = useAction({ after: refresh });
  const draft = useDraft("event-text-picker:" + projectId + ":" + initial.key, { initial: { saved: initial }, report: action.report,
    persist: (value) => api.guided.eventTextPicker(projectId, value) });
  const value = draft.value || initial;
  const row = state.rows.find((row) => row.selector === initial.key);
  const recommended = state.status === "ready" && Array.isArray(state.recommended[initial.key]) ? state.recommended[initial.key] as string[] : [];
  const visible = filteredChoices(row?.choices || [], value.selected, recommended, value.query, value.filter);
  const unsupported = value.selected.filter((id) => !(row?.choices || []).some((choice) => choice.id === id));
  const groups = [...new Set(visible.map((choice) => choice.group))];
  const dismiss = () => { void action.run(async () => { await draft.session.flush(); await api.guided.eventTextPicker(projectId, null); }, "", "cancel"); };
  const change = (patch: Partial<SourcePickerDraft>) => draft.session.edit((current) => ({ ...current, ...patch }));
  const shownSelected = visible.filter((choice) => value.selected.includes(choice.id)).length;
  if (!row) return <Modal label="Edit source selection" className="guided-sheet" onDismiss={dismiss}>
    <header className="guided-sheet-heading"><h2>Selection needs recovery</h2></header><div className="guided-sheet-body"><Message message={state.message} /><p>Your draft is retained. Close this picker and recover the source or installed handlers before reopening it.</p></div><ActionBar feedback={<Message message={action.error} />}><Button onClick={dismiss} pending={action.busy}>Close picker</Button></ActionBar>
  </Modal>;
  return <Modal label="Edit source selection" className="guided-sheet event-text-picker" dismissible={!action.busy} onDismiss={dismiss}>
    <header className="guided-sheet-heading"><p className="muted">Other event text · {row.label}</p><h2>Edit selection</h2></header>
    <div className="event-text-picker-controls">
      <p><strong>{value.selected.length} of {row.choices.length} registered entries selected</strong></p>
      <details><summary>Built-in handlers also apply · View coverage</summary><p>{row.coverage}</p><p>{row.builtins.join(", ") || "No additional built-in handlers listed."}</p></details>
      <input aria-label="Search registered entries" type="search" maxLength={200} placeholder="Search names, groups or coverage…" value={value.query} onChange={(event) => change({ query: event.target.value })} />
      <div className="event-text-picker-filters" role="group" aria-label="Filter source entries">{([ ["recommended", "Recommended", recommended.length], ["selected", "Selected", value.selected.length], ["all", "All", row.choices.length] ] as const).map(([filter, label, count]) =>
        <Button key={filter} aria-pressed={value.filter === filter} disabled={action.busy} onClick={() => change({ filter })}>{label} ({count})</Button>)}</div>
      {!!unsupported.length && <div role="alert"><p>Unsupported selections: {unsupported.join(", ")}. Remove these before saving.</p><Button onClick={() => change({ selected: value.selected.filter((id) => !unsupported.includes(id)) })}>Remove unsupported selections</Button></div>}
    </div>
    <fieldset disabled={action.busy} className="event-text-picker-list" aria-label="Registered source entries">
      {groups.map((group) => <section key={group}><h3>{group}</h3>{visible.filter((choice) => choice.group === group).map((choice) => <div key={choice.id} className="event-text-picker-row">
        <label className="toggle"><input type="checkbox" checked={value.selected.includes(choice.id)} onChange={(event) => change({ selected: toggleChoice(value.selected, choice.id, event.target.checked) })} /><span>{choice.id}</span></label>
        <details><summary>Details</summary><p>{choice.details}</p>{row.observations.filter((item) => item.includes(choice.id)).map((item, index) => <p key={index}>{item}</p>)}</details>
      </div>)}</section>)}
      {!visible.length && <p className="muted">No matching entries. Hidden selections remain selected.</p>}
    </fieldset>
    <ActionBar feedback={<><span>{value.selected.length} selected total · {shownSelected} visible · {value.selected.length - shownSelected} outside this view</span><Message message={action.error} /></>}>
      <Button disabled={action.busy} onClick={dismiss}>Cancel</Button><Button variant="primary" disabled={!!unsupported.length} pending={action.busy && action.key === "save"} onClick={() => action.run(async () => { await draft.session.flush(); await save(draft.session.getSnapshot().value!); }, "", "save")}>Save selection</Button>
    </ActionBar>
  </Modal>;
}
