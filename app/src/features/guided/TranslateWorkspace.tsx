import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { GuidedOptions, GuidedState, Job, Phase } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { VirtualList } from "../../ui/VirtualList";
import { TranslationInspector } from "./TranslationInspector";
import { activeRun, fileStatus } from "./translationView";
import { filterFiles, retainOtherScope, selectFile, selectMatching, sortFiles } from "./selection";
import "./translation.css";

const fileKey = (file: { name: string }) => file.name;
export function TranslateWorkspace({ state, phase, values, run, estimate, currentEstimate, disabled, locked, change, settings, guidance, estimateAction, runActions, review, children }: {
  state: GuidedState; phase: Phase; values: GuidedOptions; run?: Job; estimate?: Job | null; currentEstimate: boolean;
  disabled: boolean; locked: boolean; change: <K extends keyof GuidedOptions>(key: K, value: GuidedOptions[K]) => void;
  settings: () => void; guidance: () => void; estimateAction: ReactNode; runActions: ReactNode; review: (job: Job) => void; children?: ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [file, setFile] = useState("");
  const [inspecting, setInspecting] = useState(false);
  const [record, setRecord] = useState("");
  useLayoutEffect(() => { root.current?.closest(".page-body")?.scrollTo(0, 0); }, [inspecting]);
  const [anchor, setAnchor] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const rows = useMemo(() => sortFiles(state.files.filter(row => row.group === (phase === "database" ? "database" : "dialogue"))), [state.files, phase]);
  const selected = new Set(values.selected);
  const scoped = rows.filter(row => selected.has(row.name));
  const ownRuns = state.runs.filter(item => item.logicalPhase === phase && item.mode !== "estimate" && !item.keptForHistory);
  const retired = new Set(state.sourceStatus.retired || []);
  const fileRun = (name: string) => ownRuns.find(item => !retired.has(item.id) && item.files?.includes(name));
  const matching = filterFiles(rows, "all", query).filter(row => {
    const status = fileStatus(row.name, fileRun(row.name));
    return filter === "all" || filter === "selected" && selected.has(row.name) || filter === "unfinished" && status.tone !== "success" || filter === "attention" && status.tone === "warning" || filter === "saved" && status.tone === "success" || filter === "applied" && status.label === "Applied";
  });
  const names = matching.map(row => row.name);
  const records = [estimate, run].filter((item): item is Job => !!item);
  const inspected = records.find(item => item.id === record) || state.runs.find(item => item.id === record);
  const openFile = (name: string) => {
    setFile(name); setInspecting(true);
    const target = activeRun(run) || run?.scopeComplete ? run : estimate || fileRun(name);
    setRecord(target?.id || "");
  };
  const quote = currentEstimate ? estimate?.estimate : undefined;
  const cost = quote && (values.mode === "batch" ? quote.batch_nocache_cost ?? quote.batch_cost : quote.live_cost);
  const saved = scoped.filter(row => fileStatus(row.name, fileRun(row.name)).tone === "success").length;
  const paused = !!run && ["stopped", "interrupted"].includes(run.status) && run.mode === "batch" && !!run.process?.submitted;
  const title = activeRun(estimate) ? "Preparing estimate…" : run?.approval ? "Review submission" : activeRun(run) ? "Translation in progress" : paused ? "Local monitoring paused" : run?.scopeComplete ? "Translation saved" : run && ["failed", "stopped", "interrupted"].includes(run.status) ? "Saved progress needs attention" : "Ready to translate";
  return <div ref={root} className={`translation-workspace${inspecting ? " is-inspecting" : ""}`}>
    <div className="translation-intro"><span>{phase === "database" ? "Names, descriptions and interface text" : phase === "dialogue" ? "Maps, CommonEvents and Troops" : phase === "variables" ? "Update comparisons that use translated variable values" : "Translate the reviewed event and plugin sources"}</span><Button variant="quiet" onClick={guidance}>Guidance & layout</Button></div>
    <div className="translation-columns">
      <section className="translation-files" aria-label="Translation files">
        <div className="translation-file-tools"><input aria-label="Find files" type="search" value={query} placeholder="Find file, map name or 10–30…" onChange={event => setQuery(event.target.value)} /><select aria-label="Filter files" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All files</option><option value="selected">Selected</option><option value="unfinished">Unfinished</option><option value="attention">Needs attention</option><option value="saved">Saved output</option><option value="applied">Applied</option></select></div>
        <div className="translation-file-scope"><span>{scoped.length} / {rows.length} selected</span><div><Button variant="link" disabled={disabled || locked} onClick={() => change("selected", selectMatching(values.selected, names, true))}>Select {query || filter !== "all" ? "matching" : "all"}</Button><Button variant="link" disabled={disabled || locked} onClick={() => change("selected", selectMatching(values.selected, names, false))}>Clear {query || filter !== "all" ? "matching" : "all"}</Button></div></div>
        <div className="translation-file-head"><span /><span>File</span><span>Status</span></div>
        <VirtualList items={matching} itemKey={fileKey} label="Files in this task" focusKey={focus} onFocusReady={row => { row.querySelector<HTMLButtonElement>(".translation-file-open")?.focus(); setFocus(null); }} empty={<p className="muted">{rows.length ? "No files match this search." : "No files in this task."}</p>}>
          {(row, index) => { const status = fileStatus(row.name, fileRun(row.name)); return <div className={`translation-file-row${inspecting && file === row.name ? " inspected" : ""}`}>
            <input aria-label={`Include ${row.name}`} type="checkbox" disabled={disabled || locked} checked={selected.has(row.name)} onChange={event => {
                const range = event.nativeEvent instanceof MouseEvent && event.nativeEvent.shiftKey;
                const next = selectFile(values.selected.filter(name => rows.some(row => row.name === name)), names, row.name, range ? "add-range" : "toggle", anchor);
                setAnchor(next.anchor); change("selected", retainOtherScope(values.selected, rows, next.selected));
              }} />
            <button className="translation-file-open" title={[row.name, row.title].filter(Boolean).join(" · ")} onClick={() => openFile(row.name)} onKeyDown={event => {
              const next = event.key === "ArrowDown" ? Math.min(index + 1, matching.length - 1) : event.key === "ArrowUp" ? Math.max(index - 1, 0) : event.key === "Home" ? 0 : event.key === "End" ? matching.length - 1 : null;
              if (next != null) { event.preventDefault(); setFocus(matching[next].name); }
            }}>{row.name}{row.title && <small> · {row.title}</small>}</button>
            <span className={`translation-file-status ${status.tone}`} title={status.label} aria-label={status.label}><span aria-hidden="true">{status.symbol}</span><span className="translation-status-text">{status.label}</span></span>
          </div>; }}
        </VirtualList>
        <div className="translation-file-summary">{matching.length} shown · click a file to preview</div>
      </section>
      <aside className="translation-setup" aria-label="Translation setup and progress">
        <h3>{title}</h3>
        <div className="translation-provider"><strong>{state.provider.model || "Choose a model"}</strong><small>{state.provider.connection}</small><Button variant="quiet" disabled={locked} onClick={settings}>Connection & model</Button></div>
        <div className="guided-mode" role="group" aria-label="Translation method"><Button disabled={disabled || locked || !state.provider.batchSupported} aria-pressed={values.mode === "batch"} onClick={() => change("mode", "batch")}>Batch</Button><Button disabled={disabled || locked} aria-pressed={values.mode === "translate"} onClick={() => change("mode", "translate")}>Live</Button></div>
        <p className="muted">{state.provider.batchSupported ? "Batch recommended · often 50% cheaper. Results arrive when the provider finishes." : "Batch is unavailable for this connection. Live saves results as they arrive."}</p>
        {children}
        <div className="translation-estimate"><h3>Estimate → Translate</h3><p>{quote ? <><strong>{typeof cost === "number" && Number.isFinite(cost) ? "$" + cost.toFixed(4) : "Price unavailable"}</strong> · {estimate?.process?.prepared ?? "—"} requests</> : estimate ? "Generate a fresh estimate for the current selection and settings." : "Estimate locally to review cost, source lines and attached context."}</p>
          {estimateAction}
          {estimate && <Button variant="link" onClick={() => { const name = scoped[0]?.name || rows[0]?.name; if (name) { setFile(name); setRecord(estimate.id); setInspecting(true); } }}>Preview prepared requests</Button>}
          {quote && <small>Estimated cost, not a spending cap. Review before submission.</small>}
        </div>
        {run && <section className="translation-progress"><h3>{saved} / {scoped.length} files saved</h3><progress max={scoped.length || 1} value={saved} /><p>{run.message}</p>
          {!!run.process?.errors.length && <p className="translation-error">{run.process.errors.slice(0, 2).join(" · ")}</p>}
          {run.process?.uncertain ? <p className="translation-error">Submission needs reconciliation before retrying. Saved requests and results are retained.</p> : null}
          {runActions}<Button variant="link" onClick={() => review(run)}>Run details & recovery</Button>
        </section>}
        {run?.scopeComplete && <p>Saved output is ready. Apply is optional; you can continue and apply it later.</p>}
        <details className="translation-retention"><summary>Saved work & versions</summary><p>Runs retain their source, requests and results. New passes may replace the working output; earlier run copies remain in History. Applying to the game opens a review of the exact destinations, replacements and backups.</p></details>
      </aside>
      {file && <div className="translation-preview" hidden={!inspecting}>
        <TranslationInspector projectId={state.projectId} file={file} job={inspected}
          records={[...records, ...(inspected && !records.some(item => item.id === inspected.id) ? [inspected] : [])]} selectRecord={setRecord}
          close={() => { setInspecting(false); setFocus(file); }} />
      </div>}
    </div>
  </div>;
}
