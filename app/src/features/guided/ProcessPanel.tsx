import { useEffect, useRef, useState } from "react";
import type { Job, RunPayload, RunProcess } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";

const formatted = (value: unknown) => JSON.stringify(value, null, 2);

export function ProcessPanel({ job, readPayload, readProvider, compact = false }: {
  job: Job;
  readPayload?: (index: number) => Promise<RunPayload>;
  readProvider?: () => Promise<{ batches: NonNullable<RunProcess["batches"]> }>;
  compact?: boolean;
}) {
  const process = job.process;
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [remote, setRemote] = useState<RunProcess["batches"]>();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
    const [tab, setTab] = useState<"source" | "response" | "json">("source");
  const [filter, setFilter] = useState("all");
  const generation = useRef(0);
  useEffect(() => { generation.current++; setPayload(null); setRemote(undefined); setError(""); setBusy(""); setFilter("all"); if (readPayload && process?.prepared) void load(0); return () => { generation.current++; }; }, [job.id]);
  if (!process) return null;
  async function load(index: number) {
    if (!readPayload) return;
    const token = ++generation.current;
    setBusy("payload"); setError("");
    try { const value = await readPayload(index); if (token === generation.current) { setPayload(value); } }
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
    {compact ? <p className="muted">{process.prepared ?? "Unrecorded"} requests · {process.submitted ?? "Unrecorded"} submitted · {process.remaining ?? "Unrecorded"} unsent · {process.validatedFiles ?? "Unrecorded"} verified files</p>
      : <dl className="process-counts">{counts.map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count == null ? "Not recorded" : count.toLocaleString()}</dd></div>)}</dl>}
    {!compact && process.remaining != null && process.remaining > 0 && <p>{process.remaining} requests remain unsubmitted.</p>}
    {!!process.uncertain && <p>{process.uncertain} requests have uncertain submission. Check the provider before retrying.</p>}
    {!!process.duplicateSubmissions && <p>{process.duplicateSubmissions} request entries appear in multiple provider Batches. Check those jobs before submitting more work.</p>}
    {!!errors.length && <div className="process-errors">{!!process.failed && <strong>{process.failed} requests rejected</strong>}{errors.slice(0, 3).map(message => <p key={message}>{message}</p>)}</div>}
    <div className="actions">
      {readPayload && <Button disabled={!!busy || process.prepared === 0} pending={busy === "payload"} onClick={() => load(payload?.index || 0)}>Refresh saved requests</Button>}
      {!!batches.length && readProvider && <Button disabled={!!busy} pending={busy === "provider"} onClick={refreshProvider}>Read latest Batch details</Button>}
    </div>
    <Message message={error} />
    <div className="request-workspace">
      <aside className="request-list"><div role="group" aria-label="Request filters">{["all", "failed", "unsent"].map(value => <Button key={value} variant="quiet" aria-pressed={filter === value} onClick={() => setFilter(value)}>{value === "all" ? "All" : value === "failed" ? "Failed" : "Unsent"}</Button>)}</div>
        {(process.requests || Array.from({ length: process.prepared || 0 }, (_, index) => ({ index, state: "Saved", file: "", sourceItems: 0 }))).filter(row => filter === "all" || filter === "failed" && row.state === "failed" || filter === "unsent" && ["queued", "prepared"].includes(row.state)).map(row => <Button key={row.index} variant="quiet" disabled={!!busy} aria-pressed={payload?.index === row.index} onClick={() => load(row.index)}><strong>Request {row.index+1}</strong><small>{row.file || "Saved scope"} · {row.state}</small></Button>)}
      </aside>
      <section className="payload-inspector">
        {payload ? <><div className="request-selection"><strong>Request {payload.index+1} / {payload.total}</strong><span className="badge">{payload.state}</span></div>
          {payload.error != null && <pre className="process-errors">{formatted(payload.error)}</pre>}
          <p className="request-parameters">{Object.entries(payload.parameters).map(([key,value]) => `${key}: ${typeof value === "object" ? formatted(value) : String(value)}`).join(" · ")}</p>
          <div role="tablist" aria-label="Request details" className="request-tabs">{(["source", "response", "json"] as const).map(value => <Button key={value} role="tab" aria-selected={tab === value} aria-controls={`request-tab-${value}`} id={`request-tab-button-${value}`} onClick={() => setTab(value)}>{value === "source" ? "Source & context" : value === "response" ? "Response & error" : "Exact JSON"}</Button>)}</div>
          <div role="tabpanel" id={`request-tab-${tab}`} aria-labelledby={`request-tab-button-${tab}`}>
            {tab === "source" ? <div className="request-source-context"><section><h3>Source</h3><pre>{payload.source ? formatted(payload.source) : "Source is in the final retained message."}</pre></section><section><h3>Context</h3><pre>{formatted({ system: payload.system, messages: messages?.slice(0,-1), context: payload.context })}</pre></section></div>
              : tab === "response" ? <><h3>Response</h3><pre>{payload.response != null ? formatted(payload.response) : "No response body was retained for this request."}</pre><h3>Error</h3><pre>{payload.error != null ? formatted(payload.error) : "No request-specific error was retained."}</pre>{!!job.log.length && <><h3>Diagnostic log</h3><pre>{job.log.join("\n")}</pre></>}</>
              : <pre>{formatted(payload.exact)}</pre>}
          </div>
        </> : <p>{busy ? "Loading saved request…" : process.prepared ? "Choose a request to inspect." : "No requests were recorded."}</p>}
      </section>
    </div>
    <div className="process-receipts">{!!batches.length && <section><h3>Saved provider receipts</h3>{batches.map(batch => <p key={batch.id}><strong>{batch.status}</strong> · {Object.entries(batch.counts).filter(([,count]) => count).map(([key,count]) => `${count} ${key}`).join(" · ")}</p>)}</section>}
      <section><h3>Recorded usage</h3>{process.usage ? <p>{Object.entries(process.usage).map(([key,count]) => `${count.toLocaleString()} ${key.replaceAll("_", " ")}`).join(" · ")}</p> : <p>Not recorded. Local estimates do not establish billed usage.</p>}</section></div>
  </div>;
}
