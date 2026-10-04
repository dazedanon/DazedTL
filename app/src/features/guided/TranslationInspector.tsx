import { useCallback, useEffect, useRef, useState } from "react";
import type { FileTextPreview, Job, RunPayload } from "../../api/contracts";
import { api } from "../../api/client";
import { Button } from "../../ui/Button";
import { Tabs } from "../../ui/Tabs";
import { Message } from "../../ui/Feedback";
import { translatedLines } from "./translationView";
import { WorkingFileText } from "./WorkingFileText";
import { RequestContext } from "./RequestContext";
import { RequestTechnical } from "./RequestTechnical";

type View = "text" | "context" | "technical";
const views = [{ id: "text", label: "Text" }, { id: "context", label: "Context" }, { id: "technical", label: "Technical details" }] as const;
export function TranslationInspector({ projectId, file, job, history, close }: { projectId: string; file: string; job?: Job | null; history: () => void; close: () => void }) {
  const [tab, setTab] = useState<View>("text");
  const [technical, setTechnical] = useState<"payload" | "file">("payload");
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
  const needDetails = tab !== "technical" || technical === "payload";
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
  const translated = payload && translatedLines(payload);
  const missing = job ? "No prepared text was retained or linked to this file in this attempt. Click Translate to prepare a new estimate for the selected files."
    : "No text has been prepared for this file yet. Select it and click Translate to preview the text and estimate before approving API charges.";
  const position = rows.findIndex(row => row.index === index);
  const choose = (index: number) => setSelected({ job: job!.id, file, index });
  return <section className="translation-inspector" aria-label="File preview">
    <header className="translation-inspector-heading"><strong>{file}</strong><Button variant="quiet" onClick={close}>Close preview</Button></header>
    <Tabs id="translation-inspector" label="Preview content" items={views} value={tab} onChange={setTab} />
    {tab === "technical" && <Tabs id="translation-technical" label="Technical view" items={[{ id: "payload", label: "API payload" }, { id: "file", label: "File contents" }]} value={technical} onChange={setTechnical} />}
    <div className="file-preview-panel" hidden={needDetails} role="tabpanel" id="translation-technical-panel-file" aria-labelledby="translation-technical-tab-file">
      {tab === "technical" && technical === "file" && <WorkingFileText key={`${projectId}:${file}`} read={readText} />}
    </div>
    {needDetails && <div className="file-preview-panel" role="tabpanel" id={`translation-inspector-panel-${tab}`} aria-labelledby={`translation-inspector-tab-${tab}`}>
      <div className="translation-request-controls">
        {rows.length > 1 && <div className="translation-group-navigation"><span>Text group {position + 1} of {rows.length}</span><Button variant="quiet" aria-label="Previous text group" disabled={position <= 0} onClick={() => choose(rows[position - 1].index)}>Previous</Button><Button variant="quiet" aria-label="Next text group" disabled={position < 0 || position >= rows.length - 1} onClick={() => choose(rows[position + 1].index)}>Next</Button></div>}
        {!!rows.length && <Button variant="quiet" pending={pending} onClick={() => { requestCache.current.delete(key); setRefresh(value => value + 1); }}>Refresh preview</Button>}
        <Button variant="link" onClick={history}>Translation attempts</Button>
      </div>
      <Message message={error} />
      <div className="translation-reader" tabIndex={0} aria-label="Prepared request preview" aria-busy={pending}>
        {!rows.length ? <p className="muted">{missing}</p> : !payload ? <p role="status">{pending ? "Reading prepared text…" : "Use Refresh preview to try again."}</p>
          : <>{job && <p className="file-text-caption">{job.mode === "estimate" ? "Prepared estimate" : job.approval ? "Prepared for approval" : "Saved translation attempt"}{job.model && ` · ${job.model}`}{job.created && ` · ${new Date(job.created).toLocaleString()}`}</p>}
            <div hidden={tab !== "text"}>
              {payload.source && Object.keys(payload.source).length ? <table className="translation-comparison prepared-text-table"><thead><tr><th>{translated ? "Source text" : "Text to translate"}</th>{translated && <th>Saved translation</th>}</tr></thead><tbody>{Object.entries(payload.source).map(([line, text]) => <tr key={line}><td>{text}</td>{translated && <td>{translated[line]}</td>}</tr>)}</tbody></table>
                : <p className="muted">Separate source lines were not retained. The exact request is available in Technical details.</p>}
            </div>
            <div hidden={tab !== "context"}><RequestContext key={key} payload={payload} /></div>
            {tab === "technical" && job && <RequestTechnical key={key} payload={payload} job={job} />}
          </>}
      </div>
    </div>}
  </section>;
}
