import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import type { Job, NameTranslationPage, RunPayload, RunProcess } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Message } from "../../ui/Feedback";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { useAction } from "../../state/useAction";
import { RequestSource, RequestText } from "./RequestSource";
import { RequestTechnical } from "./RequestTechnical";
import { ExpandableText } from "../../ui/ExpandableText";
import { historyOutcome } from "./historyView";
import { requestAttempt, translatedLines } from "./translationView";
import { matchesRequest, requestFilter, requestOutcome, requestBatches, requestBatchOutcome, payloadForBatch, type RequestFilter, type RequestBatch } from "./requestView";
import { NameTranslationFeedback } from "./NameTranslationFeedback";

const formatted = (value: unknown) => typeof value === "string" ? value : JSON.stringify(value, null, 2);
function responseText(response: unknown) {
  const body = response && typeof response === "object" && "text" in response
    ? response.text || ("refusal" in response && typeof response.refusal === "string" ? response.refusal : null) || response : response;
  if (typeof body !== "string") return formatted(body);
  try { return formatted(JSON.parse(body)); } catch { return body; }
}
const tabs = [{ id: "source", label: "Source" }, { id: "response", label: "Response" },
  { id: "json", label: "Technical" }, { id: "run", label: "Run details" }, { id: "log", label: "Log" }] as const;
type Tab = typeof tabs[number]["id"];
type InspectorView = { index: number; tab: Tab; filter: RequestFilter; query: string; batch: string | null };
export type RequestInspectionTarget = { file: string; index: number; validation?: boolean };
const inspectorKey = (id: string) => "dazedtl:request-view:" + id;
function savedView(id: string): InspectorView {
  const fallback: InspectorView = { index: 0, tab: "source", filter: "all", query: "", batch: null };
  try {
    const value = JSON.parse(localStorage.getItem(inspectorKey(id)) || "null");
    if (!value || !Number.isSafeInteger(value.index) || value.index < 0
      || !tabs.some(tab => tab.id === value.tab) || typeof value.filter !== "string" || typeof value.query !== "string") return fallback;
    return { index: value.index, tab: value.tab, filter: requestFilter(value.filter), query: value.query.slice(0, 200), batch: typeof value.batch === "string" ? value.batch : null };
  } catch { return fallback; }
}
export function runLabel(job: Job) {
  return `${job.logicalPhase === "database" ? "Database" : job.logicalPhase === "dialogue" ? "Maps & events" : job.logicalPhase === "advanced" ? "Event / plugin codes" : job.logicalPhase === "variables" ? "Comparisons" : job.logicalPhase === "speakers" ? "Speakers" : "Translation"} · ${job.mode === "batch" ? "Batch" : job.mode === "estimate" ? "Estimate" : "Live"}`;
}
type Props = {
  job: Job; readPayload?: (index: number) => Promise<RunPayload>;
  initialRequest?: RequestInspectionTarget;
  readNames?: (offset: number) => Promise<NameTranslationPage>;
  readProvider?: () => Promise<{ batches: NonNullable<RunProcess["batches"]> }>;
  compact?: boolean; actions?: ReactNode;
};
export function ProcessPanel(props: Props) {
  return props.job.process ? <RequestProcess key={`${props.job.id}:${props.initialRequest?.file || ""}:${props.initialRequest?.index ?? ""}:${!!props.initialRequest?.validation}`} {...props} /> : null;
}
function RequestProcess({ job, readPayload, readProvider, readNames, initialRequest, actions }: Props) {
  const process = job.process!;
  const [view, setView] = useState<InspectorView>(() => initialRequest
    ? { index: initialRequest.index, tab: initialRequest.validation ? process.rejected ? "response" : "run" : "source", filter: initialRequest.validation && process.rejected ? "failed" : "all", query: initialRequest.file,
        batch: requestBatches(process, job.mode).find(batch => batch.rows.some(row => row.indices.includes(initialRequest.index)))?.id || null }
    : savedView(job.id));
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [attemptSelection, setAttemptSelection] = useState<{ request: number; attempt: number } | null>(null);
  const [remote, setRemote] = useState<RunProcess["batches"]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refreshed, setRefreshed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const provider = useAction();
  const reader = useRef<HTMLDivElement>(null);
  const refreshedIndex = useRef<number | null>(null);
  const payloadReader = useRef(readPayload);
  payloadReader.current = readPayload;
  const tabId = useId();
  const attemptTabId = useId();
  const batches = (process.batches || []).map(batch => ({ ...batch, ...remote?.find(row => row.id === batch.id), requestIndices: batch.requestIndices }));
  const groups = requestBatches({ ...process, batches }, job.mode);
  const runDetails = job.mode === "batch" && view.batch === "run-details";
  const selectedBatch = runDetails ? undefined : job.mode === "batch" ? groups.find(batch => batch.id === view.batch || batch.clarifications.some(child => child.id === view.batch))
    || (view.batch === null ? groups[0] : ["unsent", "unlinked"].includes(view.batch || "") ? groups.find(batch => batch.rows.some(row => row.indices.includes(view.index))) : undefined) : groups[0];
  const selectedProviders = selectedBatch?.provider ? [selectedBatch.provider, ...selectedBatch.clarifications] : [];
  const requests = selectedBatch?.rows || [];
  const matching = requests.filter(row => matchesRequest(row, view.filter, view.query));
  const selected = matching.find(row => row.indices.includes(view.index)) || matching[0];
  const index = selected?.index;
  function change(value: Partial<InspectorView>) {
    setView(previous => {
      const next = { ...previous, ...value };
      try { localStorage.setItem(inspectorKey(job.id), JSON.stringify(next)); } catch { /* Evidence remains backend-owned. */ }
      return next;
    });
  }
  useEffect(() => {
    let current = true;
    if (index == null || !payloadReader.current) { setBusy(false); setError(""); setPayload(null); return; }
    setBusy(true); setError(""); setRefreshed(false);
    void payloadReader.current(index).then(value => { if (current) { setPayload(value); setRefreshed(refreshedIndex.current === index); } })
      .catch(failure => { if (current) setError(failure instanceof Error ? failure.message : "Saved request unavailable."); })
      .finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [index, refresh, selected?.state, selected?.indices.length]);
  const requestPayload = payload?.index === index ? payloadForBatch(payload, selectedProviders.length ? selectedProviders.map(batch => batch.id) : undefined) : null;
  const attempts = requestPayload?.responseAttempts || [];
  const attemptIndex = Math.max(0, Math.min(attempts.length - 1, attemptSelection && attemptSelection.request === index ? attemptSelection.attempt : attempts.length - 1));
  const visiblePayload = requestPayload && requestAttempt(requestPayload, attemptIndex);
  useEffect(() => { reader.current?.scrollTo(0, 0); }, [index, view.tab, attemptIndex]);
  const position = matching.findIndex(row => row.index === index);
  function refine(value: Partial<InspectorView>) {
    const next = { ...view, ...value };
    const rows = requests.filter(row => matchesRequest(row, next.filter, next.query));
    const target = rows.find(row => row.index === index) || rows[0];
    if (target?.index !== index) refreshedIndex.current = null;
    change({ ...value, ...(target ? { index: target.index } : {}) });
  }
  const choose = (number: number, filters?: Pick<InspectorView, "filter" | "query">) => { refreshedIndex.current = null; change({ ...filters, index: number }); setRefreshed(false); };
  function openBatch(batch: RequestBatch) {
    refreshedIndex.current = null;
    setAttemptSelection(null);
    change({ batch: batch.id, index: batch.rows[0]?.index || 0, query: "", filter: "all", tab: "source" });
  }
  const errors = [...new Set([
    ...(selectedBatch?.provider ? [] : [...(process.errors || []), ...(["failed", "interrupted"].includes(job.status) && job.message ? [job.message] : [])]),
    ...(selectedProviders.length ? selectedProviders : batches).flatMap(batch => (batch.errors || []).map(error => [error.code, error.param, error.message].filter(Boolean).join(" · ")))])];
  const selectionOutcome = selected && (visiblePayload && attempts.length ? requestOutcome(visiblePayload) : selected.outcome);
  const translated = visiblePayload && translatedLines(visiblePayload);
  const comparison = translated && <table className="translation-comparison"><thead><tr><th>Original</th><th>Translation</th></tr></thead><tbody>{Object.entries(visiblePayload.source!).map(([key, text]) => <tr key={key}><td><small>{key}</small>{text}</td><td>{translated[key]}</td></tr>)}</tbody></table>;
  const requestError = visiblePayload?.error as { message?: string } | string | undefined;
  const runView = view.tab === "run" || view.tab === "log";
  return <div className="translation-process" data-view={view.tab}>
    <div className="process-overview"><div><strong>{runLabel(job)}</strong><span className="muted"> · {job.model || "Model not recorded"} · {job.files?.length || 0} files</span>
      {job.mode !== "batch" && <span className="badge">{historyOutcome(job).label}</span>}{job.keptForHistory && <span className="muted">Dismissed</span>}</div>
    </div>
    {selectedBatch && !!process.validationIssues?.length && <div className="process-validation-notice"><ActionList compact><ActionRow label={<small className="translation-error">
      Review rejected responses before applying saved output.
    </small>}><Button variant="quiet" onClick={() => {
      if (process.rejected) refine({ filter: "failed", tab: "response", query: initialRequest?.file || "" }); else change({ tab: "log" });
    }}>{process.rejected ? "Review rejected requests" : "Review validation log"}</Button></ActionRow></ActionList></div>}
    <div className={`request-workspace${job.mode === "batch" ? "" : " request-workspace--single"}`}>
      {job.mode === "batch" && <aside className="request-batch-list" aria-label="Batches in this run">
        {groups.length ? <ul className="request-batch-items">{groups.map(batch => {
          const outcome = requestBatchOutcome(batch, job);
          const count = batch.provider ? batch.provider.total : batch.rows.length;
          const files = [...new Set(batch.rows.map(row => row.file).filter(Boolean))];
          const clarificationCount = batch.clarifications.every(child => child.total != null)
            ? batch.clarifications.reduce((sum, child) => sum + child.total!, 0) : undefined;
          return <li key={batch.id}><button type="button" className="request-batch-row" aria-label={`Select ${batch.label}`}
            aria-current={selectedBatch?.id === batch.id ? "true" : undefined} onClick={() => openBatch(batch)}>
            <span className="request-batch-summary">
              <span><strong>{batch.label}</strong>{count != null && count > 0 && <span className="muted">{count.toLocaleString()} {count === 1 ? "request" : "requests"}</span>}</span>
              {outcome && <span className="request-outcome" data-state={outcome.failed ? "failed" : outcome.successful ? "finished" : "pending"}>{outcome.label}</span>}
              {outcome && outcome.summary !== `${count?.toLocaleString()} requests` && outcome.summary !== `${count?.toLocaleString()} request` && <small>{outcome.summary}</small>}
              {!!batch.clarifications.length && !outcome?.clarification && <small>{clarificationCount ? `${clarificationCount.toLocaleString()} clarification ${clarificationCount === 1 ? "request" : "requests"}` : "Includes clarification"}</small>}
              {!!files.length && <small>{files.length > 1 ? `${files.length} files · ` : ""}{files.slice(0, 2).join(", ")}{files.length > 2 ? "…" : ""}</small>}
            </span><ChevronRight size={16} aria-hidden="true" />
          </button></li>;
        })}</ul> : <p className="muted">No batches or saved requests yet.</p>}
        <div className="request-batch-tools"><Button variant="quiet" aria-pressed={runDetails && view.tab === "run"} onClick={() => change({ batch: "run-details", tab: "run" })}>Run details</Button>
          <Button variant="quiet" aria-pressed={runDetails && view.tab === "log"} onClick={() => change({ batch: "run-details", tab: "log" })}>Log</Button></div>
      </aside>}
      <section className="payload-inspector request-batch-reader" aria-label="Request details">
        {selectedBatch && job.mode === "batch" && <div className="request-batch-heading"><strong>{selectedBatch.label}</strong></div>}
        {!runDetails && <div className="request-selection">
          <div className="request-pager" aria-label="Cycle requests">
            <Button variant="quiet" aria-label="Previous request" disabled={position <= 0} onClick={() => choose(matching[position - 1].index)}>← Previous</Button>
            <strong aria-live="polite">{selected ? `Request ${position + 1} of ${matching.length}` : "No requests"}</strong>
            <Button variant="quiet" aria-label="Next request" disabled={position < 0 || position >= matching.length - 1} onClick={() => choose(matching[position + 1].index)}>Next →</Button>
          </div>
          {!runView && selectionOutcome && <span className="request-outcome" data-state={selectionOutcome.group}>{selectionOutcome.label}</span>}
          {(view.filter !== "all" || view.query) && <Button variant="quiet" onClick={() => refine({ filter: "all", query: "" })}>Show all requests</Button>}
          {!runView && readPayload && <Button className="request-refresh" variant="quiet" pending={busy} disabled={busy || index == null} onClick={() => { refreshedIndex.current = index ?? null; setRefresh(value => value + 1); }}>{refreshed ? "Updated" : "Refresh request"}</Button>}
        </div>}
        <Tabs id={tabId} label="Request content" items={runDetails ? tabs.filter(tab => tab.id === "run" || tab.id === "log") : tabs} value={view.tab} onChange={tab => change({ tab })} />
        {!runView && attempts.length > 1 && <Tabs id={attemptTabId} label="Request attempt" value={String(attemptIndex)}
          items={attempts.map((attempt, index) => ({ id: String(index), label: attempt.kind === "original" ? "Original" : "Clarification retry" }))}
          onChange={attempt => setAttemptSelection({ request: index!, attempt: Number(attempt) })} />}
        <div className="request-reader" ref={reader} tabIndex={0} aria-label="Saved request content" aria-busy={!runView && busy}
          role={!runView && attempts.length > 1 ? "tabpanel" : undefined}
          id={!runView && attempts.length > 1 ? `${attemptTabId}-panel-${attemptIndex}` : undefined}
          aria-labelledby={!runView && attempts.length > 1 ? `${attemptTabId}-tab-${attemptIndex}` : undefined}>
          {!runView && <Message message={error} />}
          {!runView && selected?.file && <p className="request-selection-file muted">{selected.file}</p>}
          {!runView && visiblePayload?.unused && <div className="request-unused">
            <p className="muted">This extra choice response was not used. The saved file uses the validated responses below.</p>
            <div className="request-references">{visiblePayload.unused.appliedRequests.filter(index => requests.some(row => row.index === index && ["validated", "saved"].includes(row.state))).map(index =>
              <Button key={index} variant="quiet" onClick={() => choose(index, { filter: "all", query: selected?.file || "" })}>View used request {index + 1}</Button>)}</div>
          </div>}
          <TabPanel id={tabId} value={view.tab}>
            {!runView && selectedBatch?.provider && !requests.length ? <p className="muted">The saved receipt does not identify this batch’s requests.</p> : view.tab === "run" ? <>
              <NameTranslationFeedback value={job.nameTranslation} read={readNames} />
              {!!process.errors.length && <Message message={process.errors.join(" · ")} />}
              <dl className="run-detail-summary">
                <div><dt>Files</dt><dd>{job.files?.join(", ") || "Not recorded"}</dd></div>
                <div><dt>Outputs</dt><dd>{job.availableOutputs == null ? "Availability not recorded" : `${job.availableOutputs.length} saved`}{job.partialOutputs?.length ? ` · ${job.partialOutputs.length} partial` : ""}{process.appliedFiles ? ` · ${process.appliedFiles} applied` : ""}</dd></div>
                {process.usage && <div><dt>Usage</dt><dd>{Object.entries(process.usage).filter(([,count]) => count > 0).map(([key,count]) => `${count.toLocaleString()} ${key.replaceAll("_", " ")}`).join(" · ")}</dd></div>}
              </dl>
              {!!process.validationIssues?.length && <div className="translation-error">{process.validationIssues.map(issue => <p key={issue.file}>{issue.file}: {issue.rejected ? `${issue.rejected} requests rejected during validation.` : "Validation mismatches were recorded; request-level details are unavailable for this older run."}</p>)}</div>}
              {!!process.uncertain && <p className="translation-error">{process.uncertain} uncertain submissions. Check provider receipts before retrying.</p>}
              {!!process.duplicateSubmissions && <p className="translation-error">{process.duplicateSubmissions} requests appear in multiple Batches.</p>}
              {actions}
            </> : view.tab === "log" ? <pre>{job.log.join("\n") || "No log was retained."}</pre>
            : view.tab === "response" ? <>
              {requestError != null && <p className="translation-error">{typeof requestError === "string" ? requestError : requestError.message || formatted(requestError)}</p>}
              {requestError == null && visiblePayload?.response == null && !attempts.length && !!errors.length && <p className="translation-error">{errors.join(" · ")}</p>}
              {visiblePayload?.responseOrigin === "validated" && <p className="muted">Previously saved translation. The original provider response was not retained.</p>}
              {visiblePayload?.responseOrigin === "log" && <p className="muted">Final attempt recovered from the saved validation log. Earlier retry bodies were not retained.</p>}
              {!visiblePayload ? <p className="muted">{busy ? "Reading saved request…" : "No request response is available. Run details retains the saved receipts and log."}</p>
                : comparison ? comparison
                : visiblePayload.response != null ? <pre>{responseText(visiblePayload.response)}</pre> : <><p className="request-response-notice muted">{selected?.providerFinished && visiblePayload.state === "submitted" ? "Response ready at the provider; waiting to download." : ["prepared", "queued"].includes(visiblePayload.state) ? "This request has not been sent." : visiblePayload.state === "submitted" ? job.mode === "batch" ? "Waiting for batch results." : "Waiting for the provider response." : visiblePayload.state === "uncertain" ? "No response is recorded for this attempt. Its submission outcome is uncertain." : visiblePayload.state === "failed" ? "This attempt failed; no response was retained." : "The original response was not retained for this older request."}</p>
                  {visiblePayload.source && <RequestText payload={visiblePayload} />}</>}
            </> : !visiblePayload ? <p className="muted" role="status">{busy ? "Reading saved request…" : error ? "Use Refresh request to try again." : "No request payload is available. Run details retains the saved receipts and log."}</p>
              : view.tab === "source" ? <RequestSource payload={visiblePayload} />
              : <><RequestTechnical key={visiblePayload.index} payload={visiblePayload} job={job} />
                  <h3>Run record</h3><p className="muted">{job.created && `${new Date(job.created).toLocaleString()} · `}{job.id}</p>
                  {!!batches.length && <><h3>Batch receipts</h3>{batches.map(batch => <p className="process-receipt" key={batch.id}><code>{batch.id}</code> · {batch.status}</p>)}
                    {readProvider && <ActionControl label="Check provider" pending={provider.busy} error={provider.error} notice={provider.notice} onClick={() => provider.run(async () => setRemote((await readProvider()).batches), "Provider details loaded.")} />}</>}
                  {job.estimate && <><h3>Saved estimate</h3><ExpandableText text={formatted(job.estimate)} label="Saved estimate" /></>}
                  {job.eventTextReview && <><h3>Event text review</h3><ExpandableText text={formatted(job.eventTextReview)} label="Event text review" /></>}
                  {visiblePayload.response != null && <><h3>{visiblePayload.responseOrigin === "validated" ? "Saved translation" : "Saved response"}</h3><ExpandableText text={formatted(visiblePayload.response)} label="Saved response" /></>}
                </>}

          </TabPanel>
        </div>
      </section>
    </div>
  </div>;
}
