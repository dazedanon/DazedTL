import { X } from "lucide-react";
import type { Job } from "../../api/contracts";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { VirtualList } from "../../ui/VirtualList";

const numeric = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const count = (value: unknown) => numeric(value) ? value.toLocaleString() : "—";
const pathKey = (path: string) => path;

export function TranslationCost({ value, mode }: { value: Record<string, unknown>; mode: string }) {
  const batch = mode === "batch";
  const costs = (batch ? [value.batch_nocache_cost, value.batch_cached_cost, value.batch_cost] : [value.live_cost ?? value.estimated_cost]).filter(numeric);
  const low = Math.min(...costs), high = Math.max(...costs);
  const prices = batch ? [["Without cache", value.batch_nocache_cost], ["With cache", value.batch_cached_cost]] as const : [];
  return <section className="translation-cost-review" aria-label="Estimated cost">
    <div className="translation-cost-total">
      <span>Estimated {batch ? "Batch" : "Live"} cost</span>
      <strong>{costs.length ? `$${low.toFixed(4)}${high > low ? `–$${high.toFixed(4)}` : ""}` : "Price unavailable"}</strong>
      <small>Final cost depends on actual usage.</small>
    </div>
    <dl className="translation-cost-tokens">
      <div><dt>Requests</dt><dd>{count(value.requests ?? value.request_count)}</dd></div>
      <div><dt>Input tokens</dt><dd>{count(value.input_tokens)}</dd></div>
      <div><dt>Est. output tokens</dt><dd>{count(value.output_tokens)}</dd></div>
    </dl>
    {prices.some(([, price]) => numeric(price)) && <dl className="translation-cost-prices">
      {prices.filter(([, price]) => numeric(price)).map(([label, price]) => <div key={label}><dt>{label}</dt><dd>${Number(price).toFixed(5)}</dd></div>)}
    </dl>}
  </section>;
}

export function TranslationReview({ job, busy, pendingKey, disabled, approvalCurrent, error, close, inspect, answer }: {
  job: Job; busy: boolean; pendingKey: string; disabled: boolean; approvalCurrent: boolean; error: string;
  close: () => void; inspect: () => void; answer: (approved: boolean) => void;
}) {
  if (!job.approval) return null;
  const batch = job.approval.kind === "batch", files = job.files || [];
  const speakers = Array.isArray(job.approval.detail.speakers) ? job.approval.detail.speakers.map(String) : [];
  const title = batch ? "Review Batch submission" : "Review speaker translation";
  return <Modal label={title} className="guided-sheet translation-review" dismissible={!busy} onDismiss={close}>
    <header className="guided-sheet-heading translation-review-heading"><h2>{title}</h2><Button variant="quiet" disabled={busy} aria-label="Close review" onClick={close}><X size={18} aria-hidden="true" /></Button></header>
    <div className="guided-sheet-body translation-review-body">
      <p className="translation-review-model">{job.model || "Saved model"} <span>· {batch ? "Batch" : "Live"} · frozen working copy</span></p>
      <TranslationCost value={job.approval.detail} mode={batch ? "batch" : "translate"} />
      <section className="translation-review-scope" aria-label="Prepared scope">
        <div className="translation-review-scope-heading"><h3>{files.length} {files.length === 1 ? "file" : "files"} to {batch ? "submit" : "check"}</h3><Button variant="quiet" disabled={busy || !files.length} onClick={inspect}>Inspect source & context</Button></div>
        {files.length <= 8 ? <ul className="guided-preview-paths">{files.map(name => <li key={name}>{name}</li>)}</ul> : <div className="guided-preview-files"><VirtualList items={files} itemKey={pathKey} label="Files to submit" empty={null}>{name => <div className="guided-preview-path">{name}</div>}</VirtualList></div>}
        {!!speakers.length && <p className="translation-review-speakers"><strong>Names to translate</strong><br />{speakers.join(", ")}</p>}
      </section>
      <p className="translation-review-notice">Submit approves this saved snapshot and incurs API charges. To include later edits, decline and prepare again. Results may replace saved working translations; earlier runs remain in History. Game files change only after Apply.</p>
    </div>
    <ActionBar feedback={<Message message={error} />}>
      <Button pending={busy && pendingKey === "run:answer:false"} disabled={disabled} onClick={() => answer(false)}>Decline</Button>
      <Button variant="primary" pending={busy && pendingKey === "run:answer:true"} disabled={disabled || !approvalCurrent} onClick={() => answer(true)}>Submit {batch ? "Batch" : "speakers"}</Button>
    </ActionBar>
  </Modal>;
}
