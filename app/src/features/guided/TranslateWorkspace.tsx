import { useMemo, useState, type ReactNode } from "react";
import { LoaderCircle } from "lucide-react";
import type { GuidedOptions, GuidedState, Job, Phase } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { Modal } from "../../ui/Modal";
import { FileSelection } from "./FileSelection";
import { TranslationInspector } from "./TranslationInspector";
import { activeRun, filePreviewRun, fileRun, fileMetricRun, fileStatus } from "./translationView";
import { retainOtherScope } from "./selection";
import "./translation.css";

export function TranslateWorkspace({ state, phase, values, run, estimate, currentEstimate, disabled, locked, change, settings, options, history, inspect, batches, children }: {
  state: GuidedState; phase: Phase; values: GuidedOptions; run?: Job; estimate?: Job | null; currentEstimate: boolean;
  disabled: boolean; locked: boolean; change: <K extends keyof GuidedOptions>(key: K, value: GuidedOptions[K]) => void;
  settings: () => void; options: () => void; history: () => void; inspect: (job: Job, file: string, index: number, validation?: boolean) => void; batches: (runId?: string) => void; children?: ReactNode;
}) {
  const [file, setFile] = useState("");
  const [inspecting, setInspecting] = useState(false);
  const [record, setRecord] = useState("");
  const rows = useMemo(() => state.files.filter(row => row.group === (phase === "database" ? "database" : "dialogue")), [state.files, phase]);
  const selected = new Set(values.selected);
  const scoped = rows.filter(row => selected.has(row.name));
  const owner = (name: string) => fileRun(state.runs, phase, name, state.sourceStatus.retired);
  const records = [estimate, run, owner(file)].filter((item): item is Job => !!item && !!item.files?.includes(file))
    .filter((item, index, all) => all.findIndex(other => other.id === item.id) === index);
  const inspected = records.find(item => item.id === record) || state.runs.find(item => item.id === record);
  const openFile = (name: string) => {
    setFile(name); setInspecting(true);
    setRecord(filePreviewRun(name, run, estimate, owner(name), currentEstimate)?.id || "");
  };
  return <div className="translation-workspace">
    <div className="translation-toolbar" aria-label="Translation setup">
      <Button variant="quiet" disabled={locked} onClick={settings} title={state.provider.connection}>{state.provider.model || "Choose a model"}</Button>
      <div className="guided-mode" role="group" aria-label="Translation method"><Button disabled={disabled || locked || !state.provider.batchSupported} title={state.provider.batchSupported ? "Recommended · often 50% cheaper" : "Unavailable for this connection"} aria-pressed={values.mode === "batch"} onClick={() => change("mode", "batch")}>Batch</Button><Button disabled={disabled || locked} aria-pressed={values.mode === "translate"} onClick={() => change("mode", "translate")}>Live</Button></div>
      <small className="translation-method-hint">{state.provider.batchSupported ? "Batch recommended · often 50% cheaper" : "Live · saves results as they arrive"}</small>
      <div className="translation-tools"><Button variant="quiet" onClick={() => batches()}>Batches</Button><Button variant="quiet" onClick={history}>Run history</Button><Button variant="quiet" onClick={options}>Options</Button></div>
    </div>
    <div className="translation-notices">{children}</div>
    <div className="translation-columns">
      <section className="translation-files" aria-label="Translation files">
        <FileSelection state={{ ...state, files: rows }} selected={scoped.map(row => row.name)} disabled={disabled || locked}
          change={names => change("selected", retainOtherScope(values.selected, rows, names))}
          inline={{ preview: openFile, previewed: inspecting ? file : undefined, columns: <><span>Status</span><span className="translation-file-cost">Cost</span><span className="translation-file-time" title="Engine processing time; excludes Batch provider waiting">Time</span><span /></>,
            details: row => {
              const fileOwner = owner(row.name), status = fileStatus(row.name, fileOwner, fileOwner?.id !== run?.id);
              const metricRun = fileMetricRun(state.runs, phase, row.name, state.sourceStatus.retired), metrics = metricRun?.process?.fileMetrics?.[row.name];
              const moving = activeRun(fileOwner) && status.tone === "active" && status.label !== "Review cost";
              const statusText = status.label !== "Ready" && <>{moving ? <LoaderCircle size={14} className="job-status-spinner" aria-hidden="true" /> : <span aria-hidden="true">{status.symbol}</span>}<span className="translation-status-text">{status.label}</span></>;
              const validation = fileOwner?.process?.validationIssues?.some(issue => issue.file === row.name);
              return <><span className={`translation-file-status ${status.tone}`} title={status.label} aria-label={status.label}>
                {statusText && validation && fileOwner ? <Button variant="link" className="translation-status-link" aria-label={`${status.label} · Review rejected requests for ${row.name}`} onKeyDown={event => event.stopPropagation()} onClick={event => {
                  event.stopPropagation(); inspect(fileOwner, row.name, fileOwner.process?.requests?.find(request => request.file === row.name && request.state === "rejected")?.index ?? 0, true);
                }}>{statusText}</Button> : statusText && fileOwner?.mode === "batch" && !!fileOwner.process?.batches?.length ? <Button variant="link" className="translation-status-link" aria-label={`${status.label} · View Batch for ${row.name}`} onKeyDown={event => event.stopPropagation()} onClick={event => { event.stopPropagation(); batches(fileOwner.id); }}>{statusText}</Button> : statusText}</span>
                <span className="translation-file-cost" title={metrics ? "Engine-reported cost from the last run that changed this file" : "Cost not recorded"}>{metrics ? `$${metrics.cost.toFixed(4)}` : "—"}</span>
                <span className="translation-file-time" title={metrics ? `${metrics.seconds.toFixed(1)} seconds of engine processing${metricRun?.mode === "batch" ? "; excludes provider waiting" : ""}` : "Time not recorded"}>{metrics ? `${metrics.seconds.toFixed(1)}s` : "—"}</span></>;
            } }} />
      </section>
      {inspecting && file && <Modal label={`File preview: ${file}`} className="request-inspector-sheet" onDismiss={() => setInspecting(false)}>
        <TranslationInspector key={`${state.projectId}:${file}`} projectId={state.projectId} file={file} job={inspected} inspect={(index, validation) => { if (inspected) inspect(inspected, file, index, validation); }}
          close={() => { setInspecting(false); }} />
      </Modal>}
    </div>
  </div>;
}
