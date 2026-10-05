import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { Job, NameTranslationPage, RunPayload, RunProcess } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { ActionControl } from "../../ui/ActionControl";
import { Message } from "../../ui/Feedback";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { VirtualList } from "../../ui/VirtualList";
import { useAction } from "../../state/useAction";
import { RequestSource } from "./RequestSource";
import { RequestTechnical } from "./RequestTechnical";
import { ExpandableText } from "../../ui/ExpandableText";
import { historyOutcome } from "./historyView";
import { translatedLines } from "./translationView";
import { NameTranslationFeedback } from "./NameTranslationFeedback";

const formatted = (value: unknown) => typeof value === "string" ? value : JSON.stringify(value, null, 2);
const tabs = [{ id: "source", label: "Source" }, { id: "response", label: "Response" },
  { id: "json", label: "Technical" }, { id: "run", label: "Run details" }, { id: "log", label: "Log" }] as const;
type Tab = typeof tabs[number]["id"];
type InspectorView = { index: number; tab: Tab; filter: string; query: string };
const inspectorKey = (id: string) => "dazedtl:request-view:" + id;
function savedView(id: string): InspectorView {
  const fallback: InspectorView = { index: 0, tab: "source", filter: "all", query: "" };
  try {
    const value = JSON.parse(localStorage.getItem(inspectorKey(id)) || "null");
    if (!value || !Number.isSafeInteger(value.index) || value.index < 0
      || !tabs.some(tab => tab.id === value.tab) || !["all", "failed", "unsent", "unresolved"].includes(value.filter) || typeof value.query !== "string") return fallback;
    return { index: value.index, tab: value.tab, filter: value.filter, query: value.query.slice(0, 200) };
  } catch { return fallback; }
}
export function runLabel(job: Job) {
  return `${job.logicalPhase === "database" ? "Database" : job.logicalPhase === "dialogue" ? "Maps & events" : job.logicalPhase === "advanced" ? "Event / plugin codes" : job.logicalPhase === "variables" ? "Comparisons" : job.logicalPhase === "speakers" ? "Speakers" : "Translation"} · ${job.mode === "batch" ? "Batch" : job.mode === "estimate" ? "Estimate" : "Live"}`;
}
type Props = {
  job: Job; readPayload?: (index: number) => Promise<RunPayload>;
  readNames?: (offset: number) => Promise<NameTranslationPage>;
  readProvider?: () => Promise<{ batches: NonNullable<RunProcess["batches"]> }>;
  compact?: boolean; actions?: ReactNode;
};
export function ProcessPanel(props: Props) {
  return props.job.process ? <RequestProcess key={props.job.id} {...props} /> : null;
}
function RequestProcess({ job, readPayload, readProvider, readNames, actions }: Props) {
  const process = job.process!;
  const [view, setView] = useState(() => savedView(job.id));
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [remote, setRemote] = useState<RunProcess["batches"]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refreshed, setRefreshed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [focus, setFocus] = useState<string | null>(() => String(savedView(job.id).index));
  const keyboardFocus = useRef(false);
  const provider = useAction();
  const reader = useRef<HTMLDivElement>(null);
  const refreshedIndex = useRef<number | null>(null);
  const payloadReader = useRef(readPayload);
  payloadReader.current = readPayload;
  const tabId = useId();
  const requests = process.requests || Array.from({ length: process.prepared || 0 }, (_, index) => ({ index, state: "Saved", file: "", sourceItems: 0 }));
  const index = requests.some(row => row.index === view.index) ? view.index : requests[0]?.index;
  const selected = requests.find(row => row.index === index);
  function change(value: Partial<InspectorView>) {
    setView(previous => {
      const next = { ...previous, ...value };
      try { localStorage.setItem(inspectorKey(job.id), JSON.stringify(next)); } catch { /* Evidence remains backend-owned. */ }
      return next;
    });
  }
  useEffect(() => {
    let current = true;
    if (index == null || !payloadReader.current) return;
    setBusy(true); setError(""); setRefreshed(false);
    void payloadReader.current(index).then(value => { if (current) { setPayload(value); setRefreshed(refreshedIndex.current === index); } })
      .catch(failure => { if (current) setError(failure instanceof Error ? failure.message : "Saved request unavailable."); })
      .finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [index, refresh, selected?.state]);
  useEffect(() => { reader.current?.scrollTo(0, 0); }, [index, view.tab]);
  const visiblePayload = payload?.index === index ? payload : null;
  const query = view.query.trim().toLocaleLowerCase();
  function matches(row: typeof requests[number], filter: string, query: string) {
    const status = filter === "all" || filter === "failed" && row.state === "failed"
      || filter === "unsent" && ["queued", "prepared"].includes(row.state)
      || filter === "unresolved" && ["submitted", "uncertain", "received"].includes(row.state);
    const found = !query || (/^#?\d+$/.test(query) ? row.index + 1 === Number(query.replace("#", "")) : (row.file || "").toLocaleLowerCase().includes(query));
    return status && found;
  }
  const matching = requests.filter(row => matches(row, view.filter, query));
  const position = matching.findIndex(row => row.index === index);
  function refine(value: Partial<InspectorView>) {
    const next = { ...view, ...value };
    const rows = requests.filter(row => matches(row, next.filter, next.query.trim().toLocaleLowerCase()));
    const target = rows.find(row => row.index === index) || rows[0];
    if (target?.index !== index) refreshedIndex.current = null;
    change({ ...value, ...(target ? { index: target.index } : {}) });
    keyboardFocus.current = false;
    setFocus(target ? String(target.index) : null);
  }
  const choose = (number: number, keyboard = false) => { refreshedIndex.current = null; change({ index: number }); setRefreshed(false); keyboardFocus.current = keyboard; setFocus(String(number)); };
  const batches = remote || process.batches || [];
  const errors = [...new Set([...(process.errors || []), ...(["failed", "interrupted"].includes(job.status) && job.message ? [job.message] : []),
    ...batches.flatMap(batch => (batch.errors || []).map(error => [error.code, error.param, error.message].filter(Boolean).join(" · ")))])];
  const counts = [process.received != null && process.prepared ? ["Received", `${process.received.toLocaleString()}/${process.prepared.toLocaleString()}`]
    : ["Requests", process.prepared], ["Failed", process.failed], ["Unsent", process.remaining]] as const;
  const translated = visiblePayload && translatedLines(visiblePayload);
  const requestError = visiblePayload?.error as { message?: string } | string | undefined;
  const runView = view.tab === "run" || view.tab === "log";
  return <div className="translation-process" data-view={view.tab}>
    <div className="process-overview"><div><strong>{runLabel(job)}</strong><span className="muted"> · {job.model || "Model not recorded"} · {job.files?.length || 0} files</span>
      <span className="badge">{historyOutcome(job).label}</span>{job.keptForHistory && <span className="muted">Dismissed</span>}</div>
      <dl className="process-counts process-counts--compact">{counts.filter(([label, count]) => count != null && (label === "Requests" || typeof count === "string" || count > 0)).map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count!.toLocaleString()}</dd></div>)}</dl>
    </div>
    <Tabs id={tabId} label="Request content" items={tabs} value={view.tab} onChange={tab => change({ tab })} />
    <div className="request-workspace">
      <aside className="request-list" aria-label="Choose a request">
        <div className="request-search"><input aria-label="Find request" type="search" maxLength={200} value={view.query} placeholder="Request # or file name" onChange={event => refine({ query: event.target.value })} />
          <div><select aria-label="Request status" value={view.filter} onChange={event => refine({ filter: event.target.value })}>
            <option value="all">All requests</option><option value="failed">Failed</option><option value="unsent">Unsent</option><option value="unresolved">Unresolved</option>
          </select><small>{matching.length.toLocaleString()} / {requests.length.toLocaleString()}</small></div></div>
        <div className="request-list-viewport" onKeyDown={event => {
          if (!matching.length || !(event.target instanceof HTMLButtonElement)) return;
          const next = event.key === "ArrowDown" ? Math.min(matching.length - 1, position + 1) : event.key === "ArrowUp" ? Math.max(0, position - 1) : event.key === "Home" ? 0 : event.key === "End" ? matching.length - 1 : null;
          if (next != null) { event.preventDefault(); choose(matching[next].index, true); }
        }}><VirtualList items={matching} itemKey={row => String(row.index)} label="Saved requests" focusKey={focus}
          onFocusReady={row => { if (keyboardFocus.current) row.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true }); setFocus(null); }}
          empty={<p className="muted">No requests match.</p>}>{row => <button type="button" className="request-row" aria-current={row.index === index ? "true" : undefined}
            tabIndex={row.index === index || position < 0 && row.index === matching[0]?.index ? 0 : -1} onClick={() => choose(row.index)}>
            <span className="request-row-number">{row.index + 1}</span><span><strong>{row.file || `Request ${row.index + 1}`}</strong><small>{row.state}{row.sourceItems ? ` · ${row.sourceItems} lines` : ""}{!row.file ? " · saved scope" : ""}</small></span>
          </button>}</VirtualList></div>
      </aside>
      <section className="payload-inspector" aria-label="Request details">
        {!runView && <div className="request-selection"><strong>{index != null ? `Request ${index + 1} / ${requests.length}` : "No saved requests"}</strong>
          {selected && <span className="badge">{visiblePayload?.state || selected.state}</span>}
          <div className="request-navigation"><Button variant="quiet" aria-label="Previous request" disabled={position <= 0} onClick={() => choose(matching[position - 1].index, true)}>←</Button>
            <Button variant="quiet" aria-label="Next request" disabled={position < 0 || position >= matching.length - 1} onClick={() => choose(matching[position + 1].index, true)}>→</Button>
            {readPayload && <Button variant="quiet" pending={busy} disabled={busy || index == null} onClick={() => { refreshedIndex.current = index ?? null; setRefresh(value => value + 1); }}>{refreshed ? "Updated" : "Refresh request"}</Button>}</div>
        </div>}
        <div className="request-reader" ref={reader} tabIndex={0} aria-label="Saved request content" aria-busy={!runView && busy}>
          {!runView && <Message message={error} />}
          <TabPanel id={tabId} value={view.tab}>
            {view.tab === "run" ? <>
              <NameTranslationFeedback value={job.nameTranslation} read={readNames} />
              <dl className="run-detail-summary">
                <div><dt>Files</dt><dd>{job.files?.join(", ") || "Not recorded"}</dd></div>
                <div><dt>Outputs</dt><dd>{job.availableOutputs == null ? "Availability not recorded" : `${job.availableOutputs.length} saved`}{job.partialOutputs?.length ? ` · ${job.partialOutputs.length} partial` : ""}{process.appliedFiles ? ` · ${process.appliedFiles} applied` : ""}</dd></div>
                {process.usage && <div><dt>Usage</dt><dd>{Object.entries(process.usage).filter(([,count]) => count > 0).map(([key,count]) => `${count.toLocaleString()} ${key.replaceAll("_", " ")}`).join(" · ")}</dd></div>}
              </dl>
              {!!process.uncertain && <p className="translation-error">{process.uncertain} uncertain submissions. Check provider receipts before retrying.</p>}
              {!!process.duplicateSubmissions && <p className="translation-error">{process.duplicateSubmissions} requests appear in multiple Batches.</p>}
              {actions}
            </> : view.tab === "log" ? <pre>{job.log.join("\n") || "No log was retained."}</pre>
            : view.tab === "response" ? <>
              {requestError != null && <p className="translation-error">{typeof requestError === "string" ? requestError : requestError.message || formatted(requestError)}</p>}
              {requestError == null && visiblePayload?.response == null && !!errors.length && <p className="translation-error">{errors.join(" · ")}</p>}
              {visiblePayload?.responseOrigin === "validated" && <p className="muted">Saved validated translation. The original provider response was not retained.</p>}
              <h3>Response</h3>{!visiblePayload ? <p className="muted">{busy ? "Reading saved request…" : "No request response is available. Run details retains the saved receipts and log."}</p>
                : translated ? <table className="translation-comparison"><thead><tr><th>Original</th><th>Translation</th></tr></thead><tbody>{Object.entries(visiblePayload.source!).map(([key, text]) => <tr key={key}><td><small>{key}</small>{text}</td><td>{translated[key]}</td></tr>)}</tbody></table>
                : visiblePayload.response != null ? <pre>{formatted(visiblePayload.response)}</pre> : <p className="muted">{["prepared", "queued"].includes(visiblePayload.state) ? "This request has not been sent." : visiblePayload.state === "submitted" ? "Waiting for the provider response." : visiblePayload.state === "failed" ? "The provider rejected this request; no translation was returned." : "The original response was not retained for this older request."}</p>}
            </> : !visiblePayload ? <p className="muted" role="status">{busy ? "Reading saved request…" : error ? "Use Refresh request to try again." : "No request payload is available. Run details retains the saved receipts and log."}</p>
              : view.tab === "source" ? <RequestSource payload={visiblePayload} />
              : <><RequestTechnical key={visiblePayload.index} payload={visiblePayload} job={job} />
                  <h3>Run record</h3><p className="muted">{job.created && `${new Date(job.created).toLocaleString()} · `}{job.id}</p>
                  {!!batches.length && <><h3>Batch receipts</h3>{batches.map(batch => <p className="process-receipt" key={batch.id}><code>{batch.id}</code> · {batch.status}</p>)}
                    {readProvider && <ActionControl label="Check provider" pending={provider.busy} error={provider.error} notice={provider.notice} onClick={() => provider.run(async () => setRemote((await readProvider()).batches), "Provider details loaded.")} />}</>}
                  {job.estimate && <><h3>Saved estimate</h3><ExpandableText text={formatted(job.estimate)} label="Saved estimate" /></>}
                  {job.eventTextReview && <><h3>Event text review</h3><ExpandableText text={formatted(job.eventTextReview)} label="Event text review" /></>}
                  {visiblePayload.response != null && <><h3>{visiblePayload.responseOrigin === "validated" ? "Validated translation" : "Saved response"}</h3><ExpandableText text={formatted(visiblePayload.response)} label="Saved response" /></>}
                </>}

          </TabPanel>
        </div>
      </section>
    </div>
  </div>;
}
