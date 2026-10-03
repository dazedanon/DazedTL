import { useEffect, useRef, useState } from "react";
import type { Job, RunPayload, RunProcess } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";

const formatted = (value: unknown) => JSON.stringify(value, null, 2);

export function ProcessPanel({ job, readPayload, readProvider }: {
  job: Job;
  readPayload?: (index: number) => Promise<RunPayload>;
  readProvider?: () => Promise<{ batches: NonNullable<RunProcess["batches"]> }>;
}) {
  const process = job.process;
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [remote, setRemote] = useState<RunProcess["batches"]>();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("1");
  const generation = useRef(0);
  useEffect(() => { generation.current++; setPayload(null); setRemote(undefined); setError(""); setBusy(""); }, [job.id]);
  if (!process) return null;
  async function load(index: number) {
    if (!readPayload) return;
    const token = ++generation.current;
    setBusy("payload"); setError("");
    try { const value = await readPayload(index); if (token === generation.current) { setPayload(value); setSelected(String(value.index+1)); } }
    catch (failure) { if (token === generation.current) setError(failure instanceof Error ? failure.message : "Payload unavailable."); }
    finally { if (token === generation.current) setBusy(""); }
  }
  async function refreshProvider() {
    if (!readProvider) return;
    const token = ++generation.current;
    setBusy("provider"); setError("");
    try { const value = await readProvider(); if (token === generation.current) setRemote(value.batches); }
    catch (failure) { if (token === generation.current) setError(failure instanceof Error ? failure.message : "Provider details unavailable."); }
    finally { if (token === generation.current) setBusy(""); }
  }
  const batches = remote || process.batches || [];
  const statuses = [...new Set(batches.map(batch => batch.status))].join(", ");
  const messages = Array.isArray(payload?.messages) ? payload.messages : null;
  const errors = [...new Set([...(process.errors || []), ...batches.flatMap(batch => (batch.errors || []).map(error =>
    [error.code, error.param, error.message].filter(Boolean).join(" · ")))])];
  const counts = [["Prepared requests", process.prepared], ["Submitted", process.submitted],
    ["Received", process.received], ["Validated requests", process.validated],
    ["Validated files", process.validatedFiles], ["Applied files", process.appliedFiles]] as const;
  return <div className="translation-process">
    <p><strong>{job.mode === "batch" ? "Batch" : job.mode === "estimate" ? "Estimate" : job.mode === "offline" ? "Local fixture" : "Live"}</strong>
      {job.model && <> · {job.model}</>}{job.files && <> · {job.files.length} {job.files.length === 1 ? "file" : "files"}</>}
      {!!statuses && <> · {remote ? "Provider" : "Saved provider"}: {statuses}</>}</p>
    {process.sourceItems != null && <p className="muted">{process.sourceItems.toLocaleString()} source items in retained requests
      {process.submittedItems != null && <> · {process.submittedItems.toLocaleString()} submitted</>}</p>}
    <dl className="process-counts">{counts.map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count == null ? "Not recorded" : count.toLocaleString()}</dd></div>)}</dl>
    {process.remaining != null && process.remaining > 0 && <p>{process.remaining} requests remain unsubmitted.</p>}
    {!!process.failed && <p className="message error">{process.failed} provider requests failed.</p>}
    {!!process.uncertain && <p>{process.uncertain} requests have uncertain submission. Check the provider before retrying.</p>}
    {!!process.duplicateSubmissions && <p>{process.duplicateSubmissions} request entries appear in multiple provider Batches. Check those jobs before submitting more work.</p>}
    {!!errors.length && <div className="process-errors">{errors.slice(0, 3).map(message => <p key={message}>{message}</p>)}</div>}
    {(process.failed || job.status === "failed" || job.status === "interrupted") && <p>{process.nextAction}</p>}
    <div className="actions">
      {readPayload && <Button disabled={!!busy || process.prepared === 0} pending={busy === "payload"} onClick={() => load(payload?.index || 0)}>Inspect payloads</Button>}
      {!!batches.length && readProvider && <Button disabled={!!busy} pending={busy === "provider"} onClick={refreshProvider}>Read latest Batch details</Button>}
    </div>
    <Message message={error} />
    {!!batches.length && <details><summary>Provider Batch status</summary>{batches.map(batch => <div key={batch.id}>
      <p><strong>{batch.status}</strong> · {Object.entries(batch.counts).filter(([, count]) => count).map(([key, count]) => `${count} ${key}`).join(" · ")}</p>
      <p className="path">{batch.id}</p>
    </div>)}<p className="muted">A provider Batch can finish with failed requests. This read does not submit, retry, or cancel work.</p></details>}
    {payload && <section className="payload-inspector">
      <div className="actions"><Button disabled={!!busy || payload.index === 0} onClick={() => load(payload.index-1)}>Previous</Button>
        <span>Request {payload.index+1} / {payload.total} · {payload.state}</span>
        <Button disabled={!!busy || payload.index+1 >= payload.total} onClick={() => load(payload.index+1)}>Next</Button>
        <label>Request <input className="request-number" type="number" min={1} max={payload.total} value={selected} onChange={event => setSelected(event.target.value)} /></label>
        <Button disabled={!!busy || !Number.isInteger(Number(selected)) || Number(selected)<1 || Number(selected)>payload.total} onClick={() => load(Number(selected)-1)}>Go</Button></div>
      <details open><summary>Source to translate</summary><pre>{payload.source ? formatted(payload.source) : "See the final source message in the exact payload."}</pre></details>
      <details><summary>Context and message order</summary><pre>{formatted({ system: payload.system,
        messageOrder: messages?.map((message, index) => ({ index: index+1, role: message.role, kind: index === messages.length-1 ? "source" : "context" })),
        contextMessages: messages?.slice(0, -1), context: payload.context })}</pre></details>
      <details><summary>Serialized parameters</summary><pre>{formatted(payload.parameters)}</pre><p className="muted">Omitted options use the provider default. Saved runs retain their original parameters.</p></details>
      <details><summary>Exact retained payload</summary><pre>{formatted(payload.exact)}</pre></details>
    </section>}
    <details><summary>Recorded usage</summary>{process.usage ? <dl className="process-counts">{Object.entries(process.usage).map(([key, count]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{count.toLocaleString()}</dd></div>)}</dl>
      : <p>Actual usage has not been recorded. A cost estimate does not establish billed usage.</p>}</details>
  </div>;
}
