import { useCallback, useEffect, useRef, useState } from "react";
import type { FileTextPreview, Job, RunPayload } from "../../api/contracts";
import { api } from "../../api/client";
import { Button } from "../../ui/Button";
import { Tabs } from "../../ui/Tabs";
import { Message } from "../../ui/Feedback";
import { requestContext } from "./translationView";
import { WorkingFileText } from "./WorkingFileText";

type View = "text" | "context" | "technical";
const views = [{ id: "text", label: "Text" }, { id: "context", label: "Context" }, { id: "technical", label: "Technical details" }] as const;
export function TranslationInspector({ projectId, file, job, history, close }: { projectId: string; file: string; job?: Job | null; history: () => void; close: () => void }) {
  const [tab, setTab] = useState<View>("text");
  const [selected, setSelected] = useState<{ job: string; file: string; index: number } | null>(null);
  const [savedPayload, setPayload] = useState<{ key: string; value: RunPayload } | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const fileCache = useRef(new Map<string, FileTextPreview>());
  const requestCache = useRef(new Map<string, RunPayload>());
  // Never present an unscoped historical request as evidence for this file.
  const rows = (job?.process?.requests || []).filter(row => row.file === file);
  const index = selected?.job === job?.id && selected?.file === file && rows.some(row => row.index === selected.index) ? selected.index : rows[0]?.index;
  const key = `${projectId}:${job?.id}:${file}:${index}`;
  const payload = savedPayload?.key === key ? savedPayload.value : null;
  const needDetails = tab !== "text";
  useEffect(() => {
    let current = true;
    setError("");
    if (!needDetails || !job || index == null) { setPending(false); return; }
    const cached = requestCache.current.get(key);
    if (cached) { setPayload({ key, value: cached }); setPending(false); return; }
    setPending(true);
    void api.guided.payload(projectId, job.id, index).then(value => {
      if (!current) return;
      if (requestCache.current.size >= 12) requestCache.current.clear();
      requestCache.current.set(key, value); setPayload({ key, value });
    }).catch(value => { if (current) setError(value instanceof Error ? value.message : "Saved request unavailable."); })
      .finally(() => { if (current) setPending(false); });
    return () => { current = false; };
  }, [projectId, job?.id, index, file, key, needDetails, refresh]);
  const readText = useCallback(async (offset: number, query: string, refresh: boolean) => {
    const prefix = `${projectId}:${file}:`, cacheKey = `${prefix}${job?.id || "unprepared"}:${query}:${offset}`;
    if (refresh) for (const key of fileCache.current.keys()) if (key.startsWith(prefix)) fileCache.current.delete(key);
    const cached = fileCache.current.get(cacheKey);
    if (cached) return cached;
    const value = await api.guided.filePreview(projectId, file, offset, query);
    if (fileCache.current.size >= 12) fileCache.current.clear();
    fileCache.current.set(cacheKey, value);
    return value;
  }, [projectId, file, job?.id]);
  const context = payload ? requestContext(payload) : [];
  const missing = job ? "Request details weren’t retained or linked to this file in this attempt. The Text tab still shows its working contents."
    : "No request has been prepared for this file yet. Translate prepares the estimate and context before you approve API charges.";
  return <section className="translation-inspector" aria-label="File preview">
    <header className="translation-inspector-heading"><strong>{file}</strong><Button variant="quiet" onClick={close}>Close preview</Button></header>
    <Tabs id="translation-inspector" label="Preview content" items={views} value={tab} onChange={setTab} />
    <div className="file-preview-panel" hidden={tab !== "text"} role="tabpanel" id="translation-inspector-panel-text" aria-labelledby="translation-inspector-tab-text">
      <WorkingFileText key={`${projectId}:${file}`} read={readText} />
    </div>
    {needDetails && <div className="file-preview-panel" role="tabpanel" id={`translation-inspector-panel-${tab}`} aria-labelledby={`translation-inspector-tab-${tab}`}>
      <div className="translation-request-controls">
        {rows.length > 1 && <label>Text group<select aria-label="Prepared text group" value={index} onChange={event => setSelected({ job: job!.id, file, index: Number(event.target.value) })}>{rows.map((row, n) => <option key={row.index} value={row.index}>{n + 1} of {rows.length} · {row.sourceItems} lines</option>)}</select></label>}
        {!!rows.length && <Button variant="quiet" pending={pending} onClick={() => { requestCache.current.delete(key); setRefresh(value => value + 1); }}>Refresh details</Button>}
        <Button variant="link" onClick={history}>Translation attempts</Button>
      </div>
      <Message message={error} />
      <div className="translation-reader" tabIndex={0} aria-label="Saved request details">
        {!rows.length ? <p className="muted">{missing}</p> : !payload ? <p role="status">{pending ? "Reading saved request…" : "Use Refresh details to try again."}</p>
          : <>{job && <p className="file-text-caption">{job.mode === "estimate" ? "Prepared estimate" : "Saved translation attempt"}{job.model && ` · ${job.model}`}{job.created && ` · ${new Date(job.created).toLocaleString()}`}</p>}
            {tab === "technical" ? <><h3>Exact API payload</h3><pre>{JSON.stringify(payload.exact, null, 2)}</pre>{payload.error != null && <><h3>Saved error</h3><pre>{JSON.stringify(payload.error, null, 2)}</pre></>}</>
              : context.length ? context.map(section => section.notes ? <details key={section.title}><summary>{section.title}</summary><pre>{section.text}</pre></details> : <section key={section.title} className="translation-matched-context"><h3>{section.title}</h3><pre>{section.text}</pre></section>)
                : <p className="muted">No separate matched context was recorded. Full instructions are available in Technical details.</p>}
          </>}
      </div>
    </div>}
  </section>;
}
