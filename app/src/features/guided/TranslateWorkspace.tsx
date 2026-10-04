import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { GuidedOptions, GuidedState, Job, Phase } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { FileSelection } from "./FileSelection";
import { TranslationInspector } from "./TranslationInspector";
import { filePreviewRun, fileStatus } from "./translationView";
import { retainOtherScope } from "./selection";
import "./translation.css";

export function TranslateWorkspace({ state, phase, values, run, estimate, currentEstimate, disabled, locked, change, settings, guidance, requestPreview, history, children }: {
  state: GuidedState; phase: Phase; values: GuidedOptions; run?: Job; estimate?: Job | null; currentEstimate: boolean;
  disabled: boolean; locked: boolean; change: <K extends keyof GuidedOptions>(key: K, value: GuidedOptions[K]) => void;
  settings: () => void; guidance: () => void; history: () => void; children?: ReactNode;
  requestPreview?: { job: string; file: string; phase: Phase } | null;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [file, setFile] = useState("");
  const [inspecting, setInspecting] = useState(false);
  const [record, setRecord] = useState("");
  useEffect(() => { if (requestPreview?.phase === phase) { setFile(requestPreview.file); setRecord(requestPreview.job); setInspecting(true); } }, [requestPreview]);
  useLayoutEffect(() => { root.current?.closest(".page-body")?.scrollTo(0, 0); }, [inspecting]);
  const rows = useMemo(() => state.files.filter(row => row.group === (phase === "database" ? "database" : "dialogue")), [state.files, phase]);
  const selected = new Set(values.selected);
  const scoped = rows.filter(row => selected.has(row.name));
  const ownRuns = state.runs.filter(item => item.logicalPhase === phase && item.mode !== "estimate");
  const retired = new Set(state.sourceStatus.retired || []);
  const fileRun = (name: string) => ownRuns.find(item => !retired.has(item.id) && !item.retiredFiles?.includes(name) && item.files?.includes(name));
  const records = [estimate, run, fileRun(file)].filter((item): item is Job => !!item && !!item.files?.includes(file))
    .filter((item, index, all) => all.findIndex(other => other.id === item.id) === index);
  const inspected = records.find(item => item.id === record) || state.runs.find(item => item.id === record);
  const openFile = (name: string) => {
    setFile(name); setInspecting(true);
    setRecord(filePreviewRun(name, run, estimate, fileRun(name), currentEstimate)?.id || "");
  };
  return <div ref={root} className={`translation-workspace${inspecting ? " is-inspecting" : ""}`}>
    <div className="translation-toolbar" aria-label="Translation setup">
      <Button variant="quiet" disabled={locked} onClick={settings} title={state.provider.connection}>{state.provider.model || "Choose a model"}</Button>
      <div className="guided-mode" role="group" aria-label="Translation method"><Button disabled={disabled || locked || !state.provider.batchSupported} title={state.provider.batchSupported ? "Recommended · often 50% cheaper" : "Unavailable for this connection"} aria-pressed={values.mode === "batch"} onClick={() => change("mode", "batch")}>Batch</Button><Button disabled={disabled || locked} aria-pressed={values.mode === "translate"} onClick={() => change("mode", "translate")}>Live</Button></div>
      <small className="translation-method-hint">{state.provider.batchSupported ? "Batch recommended · often 50% cheaper" : "Live · saves results as they arrive"}</small>
      <div className="translation-tools"><Button variant="quiet" onClick={history}>Run history</Button><Button variant="quiet" onClick={guidance}>Options</Button></div>
    </div>
    <div className="translation-notices">{children}{locked && <p className="muted">Selection is fixed while this run is active. You can still search and preview files.</p>}</div>
    <div className="translation-columns">
      <section className="translation-files" aria-label="Translation files">
        <FileSelection state={{ ...state, files: rows }} selected={scoped.map(row => row.name)} disabled={disabled || locked}
          change={names => change("selected", retainOtherScope(values.selected, rows, names))}
          inline={{ preview: openFile, columns: <><span>Status</span><span className="translation-file-cost">Cost</span><span className="translation-file-time" title="Engine processing time; excludes Batch provider waiting">Time</span><span /></>,
            details: row => {
              const owner = fileRun(row.name), status = fileStatus(row.name, owner, owner?.id !== run?.id), metrics = owner?.process?.fileMetrics?.[row.name];
              return <><span className={`translation-file-status ${status.tone}`} title={status.label} aria-label={status.label}><span aria-hidden="true">{status.symbol}</span><span className="translation-status-text">{status.label}</span></span>
                <span className="translation-file-cost" title={metrics ? "Engine-reported cost for this saved run" : "Cost not recorded"}>{metrics ? `$${metrics.cost.toFixed(4)}` : "—"}</span>
                <span className="translation-file-time" title={metrics ? `${metrics.seconds.toFixed(1)} seconds of engine processing${owner?.mode === "batch" ? "; excludes provider waiting" : ""}` : "Time not recorded"}>{metrics ? `${metrics.seconds.toFixed(1)}s` : "—"}</span></>;
            } }} />
      </section>
      {file && <div className="translation-preview" hidden={!inspecting}>
        <TranslationInspector projectId={state.projectId} file={file} job={inspected} history={history}
          close={() => { setInspecting(false); }} />
      </div>}
    </div>
  </div>;
}
