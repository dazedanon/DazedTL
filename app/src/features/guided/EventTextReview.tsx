import { useState } from "react";
import type { EngineValue, EventTextState } from "../../api/contracts";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { manualSources } from "./eventTextSelection";

export interface SourceReview { state: EventTextState; revision: number; values: Record<string, EngineValue> }
export function EventTextReview({ review, busy, error, cancel, accept }: {
  review: SourceReview; busy: boolean; error: string; cancel: () => void; accept: (reason: string, accepted: boolean) => void;
}) {
  const manual = manualSources(review.state, review.values);
  const [reason, setReason] = useState(review.state.manualReason || review.state.previousManualReason || "");
  const [accepted, setAccepted] = useState(false);
  const enabled = review.state.rows.filter((row) => review.values[row.key]);
  return <Modal label="Review event text sources" className="guided-sheet" dismissible={!busy} onDismiss={cancel}>
    <header className="guided-sheet-heading"><h2>Review source choices</h2></header>
    <div className="guided-sheet-body">
      <p>Only these supported settings will be saved for translation. Reviewing sources does not start a run.</p>
      {review.values.AUTONAMEPOPUP101 === true && <p>Saved AutoNamePopup handling also processes supported actor-name changes independently of source 320.</p>}
      {enabled.map((row) => <section className="event-text-source" key={row.key}><h3>{row.label}{manual.includes(row.key) ? " · Manual override" : " · Investigation recommendation"}</h3>
        <p>{row.coverage}</p>
        {row.key === "CODE122" && <p>Starting variable IDs: {String(review.values.CODE122_VAR_RANGES)}</p>}
        {row.selector && <p className="path">Registered selections: {(review.values[row.selector] as string[]).join(", ") || "None"}</p>}
        {!!row.builtins.length && <p>Built-in coverage also enabled: {row.builtins.join(", ")}. No individual built-in switches.</p>}
        {!!row.exclusions.length && <p>Reported exclusions: {row.exclusions.join("; ")}</p>}
      </section>)}
      {!!manual.length && <div className="event-text-risk"><strong>Manual coverage confirmation</strong><p>These choices differ from verified safe recommendations, or have no current investigation. Translating internal IDs, filenames, script arguments or logic strings can break the game. Reported exclusions do not isolate occurrences sharing enabled coverage.</p>
        <label>Reason for these manual choices<textarea aria-label="Manual override reason" maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <label className="toggle"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} />I reviewed every affected use, including built-ins, and accept this actual coverage.</label>
      </div>}
    </div>
    <ActionBar feedback={<Message message={error} />}><Button disabled={busy} onClick={cancel}>Cancel</Button><Button variant="primary" pending={busy} disabled={!!manual.length && (!accepted || !reason.trim())} onClick={() => accept(reason, accepted)}>Confirm source choices</Button></ActionBar>
  </Modal>;
}
