import { useEffect, useRef, useState } from "react";
import type { Job, RunPayload } from "../../api/contracts";
import { api } from "../../api/client";
import { Button } from "../../ui/Button";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { Message } from "../../ui/Feedback";
import { requestContext, translatedLines } from "./translationView";

type View = "source" | "translation" | "exact";
const views = [{ id: "source", label: "Source & context" }, { id: "translation", label: "Translation" }, { id: "exact", label: "Exact payload" }] as const;
export function TranslationInspector({ projectId, file, checked, job, records, selectRecord, close }: { projectId: string; file: string; checked: boolean; job?: Job | null; records: Job[]; selectRecord: (id: string) => void; close: () => void }) {
  const [tab, setTab] = useState<View>("source");
  const [selected, setSelected] = useState<{ job: string; file: string; index: number } | null>(null);
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const sequence = useRef(0);
  const reader = useRef<HTMLDivElement>(null);
  const requests = (job?.process?.requests || []).filter(row => row.file === file);
  // Older runs without provenance remain inspectable, with their actual scope labeled.
  const unscoped = !requests.length && (job?.process?.requests || []).every(row => !row.file);
  const rows = unscoped ? job?.process?.requests || [] : requests;
  const index = selected?.job === job?.id && selected?.file === file && rows.some(row => row.index === selected.index) ? selected.index : rows[0]?.index;
  const state = rows.find(row => row.index === index)?.state;
  useEffect(() => {
    const token = ++sequence.current;
    setError(""); setPayload(null);
    if (!job || index == null) { setPending(false); return; }
    setPending(true);
    void api.guided.payload(projectId, job.id, index).then(value => { if (token === sequence.current) setPayload(value); })
      .catch(failure => { if (token === sequence.current) setError(failure instanceof Error ? failure.message : "Saved request unavailable."); })
      .finally(() => { if (token === sequence.current) setPending(false); });
    return () => { sequence.current++; };
  }, [projectId, job?.id, index, file, refresh]);
  // Results announce availability without replacing a reader's current content or scroll position.
  useEffect(() => { reader.current?.scrollTo(0, 0); }, [job?.id, index, file, tab]);
  const translated = payload && translatedLines(payload);
  return <section className="translation-inspector" aria-label="File preview">
    <header className="translation-inspector-heading"><div><strong>{file}</strong><span className="translation-preview-check">{checked ? " · checked" : " · preview only (not checked)"}</span><small>{job ? `${job.mode === "estimate" ? "Prepared estimate" : "Saved run"} · ${job.model || "Model not recorded"}` : "Preview before translation"}</small></div><Button variant="quiet" onClick={close}>Files & setup</Button></header>
    <Tabs id="translation-inspector" label="Preview content" items={views} value={tab} onChange={setTab} />
    <div className="translation-request-controls">
      <label>Record<select aria-label="Saved record" value={job?.id || ""} onChange={event => selectRecord(event.target.value)}><option value="">Choose a record</option>{records.map(item => <option key={item.id} value={item.id}>{item.mode === "estimate" ? "Estimate" : "Translation"} · {item.created ? new Date(item.created).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : item.status}</option>)}</select></label>
      {!!rows.length && <label>Request<select value={index} disabled={pending} onChange={event => setSelected({ job: job!.id, file, index: Number(event.target.value) })}>{rows.map((row, n) => <option key={row.index} value={row.index}>{n + 1} of {rows.length} · {row.sourceItems} lines · {row.state}</option>)}</select></label>}
      {!!rows.length && <Button variant="quiet" pending={pending} disabled={pending} onClick={() => setRefresh(value => value + 1)}>Refresh</Button>}
      {payload && state !== payload.state && <small role="status">New results available. Refresh when ready.</small>}
    </div>
    <Message message={error} />
    {unscoped && !!rows.length && <p className="muted">This older run has no file-level request links. Showing its saved request scope.</p>}
    <div className="translation-reader" ref={reader} tabIndex={0} aria-label="Saved request content">
      <TabPanel id="translation-inspector" value={tab}>
        {!payload ? <p className="muted">{pending ? "Reading saved request…" : !job ? "Generate an estimate to preview the lines and context prepared for translation." : !rows.length ? "No prepared requests are linked to this file in this record. It may have no remaining translatable text; History retains earlier runs." : error ? "Use Refresh to try reading this saved request again." : "Select a request to preview it."}</p>
          : tab === "exact" ? <pre>{JSON.stringify(payload.exact, null, 2)}</pre>
          : tab === "source" ? <><h3>Lines to translate</h3>{payload.source ? <dl className="translation-source-lines">{Object.entries(payload.source).map(([key, text]) => <div key={key}><dt>{key}</dt><dd>{text}</dd></div>)}</dl> : <p>Source is contained in the retained messages below.</p>}
            <details open><summary>Attached context & messages</summary><pre>{requestContext(payload)}</pre></details></>
          : <><p className="muted">{job?.mode === "estimate" ? "Results are saved under the translation record." : job?.availableOutputs?.includes(file) ? "Translated file verified · saved response below." : payload.state === "validated" ? "Validated response saved." : "Provider response · file validation may still be pending."}</p>
            {translated ? <table className="translation-comparison"><thead><tr><th>Original</th><th>Translation</th></tr></thead><tbody>{Object.entries(payload.source!).map(([key, text]) => <tr key={key}><td><small>{key}</small>{text}</td><td>{translated[key]}</td></tr>)}</tbody></table>
              : payload.response != null ? <><p>The saved response cannot be matched to individual lines unambiguously.</p><pre>{JSON.stringify(payload.response, null, 2)}</pre></> : <p>No response has been saved for this request yet.</p>}
            {payload.error != null && <><h3>Request error</h3><pre>{JSON.stringify(payload.error, null, 2)}</pre></>}</>}
      </TabPanel>
    </div>
  </section>;
}
