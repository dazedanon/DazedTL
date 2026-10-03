import { useEffect, useId, useRef, useState } from "react";
import type { Job, RunPayload, RunProcess } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";

const formatted = (value: unknown) => JSON.stringify(value, null, 2);
const tabs = ["source", "response", "json"] as const;
type Tab = typeof tabs[number];
const contextText = (payload: RunPayload) => [
  payload.system != null ? "System instructions\n" + (typeof payload.system === "string" ? payload.system : formatted(payload.system)) : "",
  ...(Array.isArray(payload.messages) ? payload.messages.slice(0, -1).map(message => {
    if (!message || typeof message !== "object" || Array.isArray(message)) return formatted(message);
    const value = message as { role?: string; content?: unknown };
    return (value.role || "Saved") + " message\n" + (typeof value.content === "string" ? value.content : formatted(value.content));
  }) : []),
  payload.context != null ? "Matched context\n" + (typeof payload.context === "string" ? payload.context : formatted(payload.context)) : "",
].filter(Boolean).join("\n\n") || "No separate context was retained. Exact JSON contains the saved request.";

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
  const [tab, setTab] = useState<Tab>("source");
  const [filter, setFilter] = useState("all");
  const generation = useRef(0);
  const pending = useRef(false);
  const tabList = useRef<HTMLDivElement>(null);
  const tabId = useId();
  useEffect(() => { generation.current++; pending.current = false; setPayload(null); setRemote(undefined); setError(""); setBusy(""); setFilter("all"); setTab("source"); if (readPayload && process?.prepared) void load(0); return () => { generation.current++; }; }, [job.id]);
  if (!process) return null;
  async function load(index: number) {
    if (!readPayload || pending.current) return;
    pending.current = true;
    const token = ++generation.current;
    setBusy("payload"); setError("");
    try { const value = await readPayload(index); if (token === generation.current) { setPayload(value); } }
    catch (failure) { if (token === generation.current) setError(failure instanceof Error ? failure.message : "Payload unavailable."); }
    finally { if (token === generation.current) { pending.current = false; setBusy(""); } }
  }
  async function refreshProvider() {
    if (!readProvider || pending.current) return;
    pending.current = true;
    const token = ++generation.current;
    setBusy("provider"); setError("");
    try { const value = await readProvider(); if (token === generation.current) setRemote(value.batches); }
    catch (failure) { if (token === generation.current) setError(failure instanceof Error ? failure.message : "Provider details unavailable."); }
    finally { if (token === generation.current) { pending.current = false; setBusy(""); } }
  }
  function showTab(value: Tab, focus = false) {
    setTab(value);
    if (focus) tabList.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[tabs.indexOf(value)]?.focus();
  }
  const batches = remote || process.batches || [];
  const statuses = [...new Set(batches.map(batch => batch.status))].join(", ");
  const errors = [...new Set([...(process.errors || []), ...batches.flatMap(batch => (batch.errors || []).map(error =>
    [error.code, error.param, error.message].filter(Boolean).join(" · ")))])];
  const counts = [["Prepared requests", process.prepared], ["Submitted", process.submitted],
    ["Received", process.received], ["Validated requests", process.validated],
    ["Validated files", process.validatedFiles], ["Applied files", process.appliedFiles]] as const;
  const schema = payload?.parameters.response_format as { type?: string; json_schema?: { strict?: boolean } } | undefined;
  const tokenLimit = payload?.parameters.max_completion_tokens ?? payload?.parameters.max_tokens;
  return <div className={`translation-process${compact ? " translation-process--compact" : ""}`}>
    <p><strong>{job.mode === "batch" ? "Batch" : job.mode === "estimate" ? "Estimate" : job.mode === "offline" ? "Local fixture" : "Live"}</strong>
      {job.model && <> · {job.model}</>}{job.files && <> · {job.files.length} {job.files.length === 1 ? "file" : "files"}</>}
      {!!statuses && <> · {remote ? "Provider" : "Saved provider"}: {statuses}</>}</p>
    <dl className={`process-counts${compact ? " process-counts--compact" : ""}`}>{[...counts, ...(process.remaining != null ? [["Unsent", process.remaining] as const] : [])].map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count == null ? "Not recorded" : count.toLocaleString()}</dd></div>)}</dl>
    {!!process.uncertain && <p>{process.uncertain} requests have uncertain submission. Check the provider before retrying.</p>}
    {!!process.duplicateSubmissions && <p>{process.duplicateSubmissions} request entries appear in multiple provider Batches. Check those jobs before submitting more work.</p>}
    {!!errors.length && <div className={`process-errors${compact ? " process-errors--compact" : ""}`}>{!!process.failed && <strong>{process.failed} requests rejected</strong>}{(compact ? errors.slice(0, 1) : errors.slice(0, 3)).map(message => <p key={message}>{message}</p>)}{errors.length > (compact ? 1 : 3) && <Button variant="link" onClick={() => showTab("response", true)}>View all {errors.length} errors</Button>}</div>}
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
          <p className="request-parameters">{typeof payload.parameters.model === "string" && <span>{payload.parameters.model}</span>}{payload.source && <span>{Object.keys(payload.source).length} source lines</span>}{typeof tokenLimit === "number" && <span>{tokenLimit.toLocaleString()} token limit</span>}{schema?.type === "json_schema" && <span>{schema.json_schema?.strict ? "Strict JSON schema" : "JSON schema"}</span>}{payload.error != null && <Button variant="link" onClick={() => showTab("response", true)}>Request error recorded</Button>}</p>
          <div ref={tabList} role="tablist" aria-label="Request details" className="request-tabs" onKeyDown={event => {
            const index = tabs.indexOf(tab);
            const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
            if (next != null) { event.preventDefault(); showTab(tabs[next], true); }
          }}>{tabs.map(value => <Button key={value} role="tab" tabIndex={tab === value ? 0 : -1} aria-selected={tab === value} aria-controls={`${tabId}-${value}`} id={`${tabId}-button-${value}`} onClick={() => showTab(value)}>{value === "source" ? "Source & context" : value === "response" ? "Response & error" : "Exact JSON"}</Button>)}</div>
          <div key={`${payload.index}-${tab}`} role="tabpanel" id={`${tabId}-${tab}`} aria-labelledby={`${tabId}-button-${tab}`}>
            {tab === "source" ? <div className="request-source-context"><section><h3>Source</h3><pre tabIndex={0} role="region" aria-label="Source payload">{payload.source ? formatted(payload.source) : "Source is in the final retained message."}</pre></section><section><h3>Context</h3><pre tabIndex={0} role="region" aria-label="Saved context">{contextText(payload)}</pre></section></div>
              : tab === "response" ? <><h3>Response</h3><pre tabIndex={0} role="region" aria-label="Saved response">{payload.response != null ? formatted(payload.response) : "No response body was retained for this request."}</pre><h3>Error</h3><pre tabIndex={0} role="region" aria-label="Request error">{payload.error != null ? formatted(payload.error) : "No request-specific error was retained."}</pre>{!!errors.length && <><h3>Run & provider errors</h3><pre tabIndex={0} role="region" aria-label="Run and provider errors">{errors.join("\n\n")}</pre></>}{!!job.log.length && <><h3>Diagnostic log</h3><pre tabIndex={0} role="region" aria-label="Diagnostic log">{job.log.join("\n")}</pre></>}</>
              : <pre tabIndex={0} role="region" aria-label="Exact request JSON">{formatted(payload.exact)}</pre>}
          </div>
        </> : <p>{busy ? "Loading saved request…" : process.prepared ? "Choose a request to inspect." : "No requests were recorded."}</p>}
      </section>
    </div>
    <div className="process-receipts">{!!batches.length && <section><h3>Saved provider receipts</h3>{batches.map(batch => <p key={batch.id}><strong>{batch.status}</strong> · {Object.entries(batch.counts).filter(([,count]) => count).map(([key,count]) => `${count} ${key}`).join(" · ")}</p>)}</section>}
      <section><h3>Recorded usage</h3>{process.usage ? <p>{Object.entries(process.usage).map(([key,count]) => `${count.toLocaleString()} ${key.replaceAll("_", " ")}`).join(" · ")}</p> : <p>Not recorded. Local estimates do not establish billed usage.</p>}</section></div>
  </div>;
}
