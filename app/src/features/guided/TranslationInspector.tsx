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

type View = "text" | "context" | "technical" | "file";
const views = [{ id: "text", label: "Text" }, { id: "context", label: "Context" }, { id: "technical", label: "Technical details" }, { id: "file", label: "File contents" }] as const;
export function TranslationInspector({ projectId, file, job, inspect, close }: { projectId: string; file: string; job?: Job | null; inspect: (index: number) => void; close: () => void }) {
  const [tab, setTab] = useState<View>("text");
  const [fileOpened, setFileOpened] = useState(false);
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
  useEffect(() => {
    let current = true;
    setError("");
    if (!job || index == null) { setPending(false); return; }
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
  }, [projectId, job?.id, index, file, key, refresh]);
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
  const missing = job?.process?.noRequestFiles?.includes(file) ? "This file produced no new requests in this pass." : job ? "No prepared text was retained or linked to this file in this attempt. Click Translate to prepare a new estimate for the selected files."
    : "No text has been prepared for this file yet. Select it and click Translate to preview the text and estimate before approving API charges.";
  const position = rows.findIndex(row => row.index === index);
  const choose = (index: number) => setSelected({ job: job!.id, file, index });
  const parameters = payload?.parameters as Record<string, unknown> | null;
  const model = String(parameters?.model || job?.model || "Model not recorded");
  return <section className="translation-inspector" aria-label="File preview">
    <header className="translation-inspector-heading"><div><strong>{file}</strong>
      {job && !!rows.length && <small>{job.mode === "estimate" ? "Prepared estimate" : job.approval ? "Prepared for approval" : "Saved translation attempt"} · {model}{job.created && ` · ${new Date(job.created).toLocaleString()}`}</small>}
    </div><Button variant="quiet" onClick={close}>Close preview</Button></header>
    <Tabs id="translation-inspector" label="Preview content" items={views} value={tab} onChange={value => { setTab(value); if (value === "file") setFileOpened(true); }} />
    <div className="file-preview-panel" hidden={tab !== "file"} role="tabpanel" id="translation-inspector-panel-file" aria-labelledby="translation-inspector-tab-file">
      {fileOpened && <WorkingFileText key={`${projectId}:${file}`} read={readText} />}
    </div>
    <div className="file-preview-panel" hidden={tab === "file"}>
      {!!rows.length && <div className="translation-request-controls">
        {rows.length > 1 && <div className="translation-group-navigation" role="group" aria-label="Text group navigation"><span>Text group {position + 1} of {rows.length}</span><Button variant="quiet" aria-label="Previous text group" disabled={position <= 0} onClick={() => choose(rows[position - 1].index)}>Previous</Button><Button variant="quiet" aria-label="Next text group" disabled={position < 0 || position >= rows.length - 1} onClick={() => choose(rows[position + 1].index)}>Next</Button></div>}
        <div className="translation-request-actions">
          <Button variant="quiet" pending={pending} onClick={() => { requestCache.current.delete(key); setRefresh(value => value + 1); }}>Refresh preview</Button>
          {index != null && <Button variant="quiet" onClick={() => inspect(index)}>{job?.mode === "estimate" ? "View estimate" : "View translation attempt"}</Button>}
        </div>
      </div>}
      <Message message={error} />
      {views.filter(view => view.id !== "file").map(view => <div className={`translation-reader${view.id === "technical" ? " translation-reader--technical" : ""}`} key={`${key}:${view.id}`} hidden={tab !== view.id} role="tabpanel" id={`translation-inspector-panel-${view.id}`} aria-labelledby={`translation-inspector-tab-${view.id}`} tabIndex={view.id === "technical" && payload ? undefined : 0} aria-busy={pending}>
        {!rows.length ? <p className="muted">{missing}</p> : !payload ? error ? null : <p role="status">{pending ? "Reading prepared text…" : "Use Refresh preview to try again."}</p>
          : <div className={view.id === "context" ? "translation-context-reader" : view.id === "technical" ? "translation-technical-reader" : undefined}>
            {view.id === "text" ? payload.source && Object.keys(payload.source).length ? <table className="translation-comparison prepared-text-table"><thead><tr><th>{translated ? "Source text" : "Text to translate"}</th>{translated && <th>Saved translation</th>}</tr></thead><tbody>{Object.entries(payload.source).map(([line, text]) => <tr key={line}><td>{text}</td>{translated && <td>{translated[line]}</td>}</tr>)}</tbody></table>
              : <p className="muted">Separate source lines were not retained. The exact request is available in Technical details.</p>
              : view.id === "context" ? <RequestContext payload={payload} compact={false} />
              : job && <RequestTechnical payload={payload} job={job} compact={false} showModel={false} />}
          </div>}
      </div>)}
    </div>
  </section>;
}
