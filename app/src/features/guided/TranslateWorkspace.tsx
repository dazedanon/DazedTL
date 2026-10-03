import { useState } from "react";
import type { GuidedState, Job } from "../../api/contracts";
import { Button } from "../../ui/Button";

export function TranslateWorkspace({ state, scope, mode, run, estimate, pending, disabled, scopeChange, modeChange, files, settings, guidance, requests }: {
  state: GuidedState; scope: "database" | "dialogue"; mode: "batch" | "translate";
  run?: Job; estimate?: Job | null; pending: boolean; disabled: boolean;
  scopeChange: (scope: "database" | "dialogue") => void; modeChange: (mode: "batch" | "translate") => void;
  files: () => void; settings: () => void; guidance: () => void; requests: (run: Job) => void;
}) {
  const selected = new Set(state.preferences.values.selected);
  const rows = state.files.filter(file => file.group === scope && selected.has(file.name));
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const matching = rows.filter(file => (file.name + " " + file.title).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const pageSize = 25;
  const lastPage = Math.max(0, Math.ceil(matching.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const applied = new Set(state.readiness.applied);
  const edited = new Set(state.readiness.runtime_edited);
  const process = run?.process;
  const quote = estimate?.estimate;
  const cost = quote && Number(mode === "batch" ? quote.batch_nocache_cost ?? quote.batch_cost : quote.live_cost);
  const active = !!run && ["running", "waiting"].includes(run.status);
  const providerPending = process?.batches?.some(batch => ["validating", "in_progress", "finalizing"].includes(batch.status));
  const monitoringPaused = !!run && ["stopped", "interrupted"].includes(run.status) && run.phase?.startsWith("poll") && !!process?.submitted;
  const errors = process?.errors || [];
  const preparationIssue = estimate?.mode === "estimate" && ["failed", "stopped", "interrupted"].includes(estimate.status);
  const details = active || monitoringPaused ? run : estimate || run;
  const status = pending ? "Preparing a local estimate…" : run?.approval ? run.approval.kind === "batch" ? "Ready for Batch approval" : "Speaker names need review" : monitoringPaused ? "Local monitoring paused" : providerPending ? "Batch processing" : active ? run?.phase === "consume" ? "Validating and saving output" : "Preparing translation" : preparationIssue ? "Local preparation " + estimate!.status : run?.status === "complete" ? "Translation output saved" : run && ["failed", "stopped", "interrupted"].includes(run.status) ? "Saved progress needs attention" : "Ready for translation";
  return <div className="translate-overview">
    <div className="translate-toolbar">
      <label>Text scope<select value={scope} disabled={disabled} onChange={event => scopeChange(event.target.value as typeof scope)}>
        <option value="database">Database & interface</option><option value="dialogue">Dialogue & choices</option>
      </select></label>
      <div className="translate-model"><small>Model</small><strong>{state.provider.model || "Choose a model"}</strong></div>
      <div className="guided-mode" role="group" aria-label="Translation mode">
        <Button disabled={disabled} aria-pressed={mode === "batch"} onClick={() => modeChange("batch")}>Batch</Button>
        <Button disabled={disabled} aria-pressed={mode === "translate"} onClick={() => modeChange("translate")}>Live API</Button>
      </div>
      <Button disabled={disabled} onClick={settings}>Settings</Button>
    </div>
    <dl className="translate-metrics">
      <div><dt>Saved output files</dt><dd>{rows.filter(file => state.readiness.outputs.includes(file.name)).length} <small>/ {rows.length}</small></dd></div>
      <div><dt>Verified game files</dt><dd>{rows.filter(file => applied.has(file.name) && !edited.has(file.name)).length} <small>/ {rows.length}</small></dd></div>
      <div><dt>Planned requests</dt><dd>{estimate?.process?.prepared ?? "-"}</dd></div>
      <div><dt>Provider work</dt><dd>{run?.approval ? "Awaiting approval" : providerPending ? "Processing" : active ? "Preparing" : process?.uncertain ? "Needs reconciliation" : process?.failed ? "Requests rejected" : process?.submitted ? "Finished" : "Not submitted"}</dd></div>
      <div><dt>Local estimate</dt><dd>{Number.isFinite(cost) ? "$" + cost!.toFixed(4) : "Not calculated"}</dd></div>
    </dl>
    <div className="translate-status"><div><strong>{status}</strong><p>{pending && estimate ? estimate.message : active || monitoringPaused ? run!.message : preparationIssue ? estimate!.message : "Translate prepares remaining work with current settings, then opens cost review."}</p>
      {active && run.progress && <progress max={run.progress.total || 1} value={run.progress.current} />}
    </div>{details && <Button disabled={disabled} onClick={() => requests(details)}>View requests</Button>}</div>
    {!!errors.length && <div className="translate-run-error" role="status"><strong>{process?.failed || "Saved"} {process?.failed ? "requests rejected" : "run needs attention"}</strong>
      <p>{errors.slice(0, 2).join(" · ")}</p><small>History and verified results are retained automatically.</small></div>}
    <div className="translate-files-heading"><div><h3>Selected files</h3><p>{rows.length} files · {scope === "database" ? "Names, descriptions and interface terms" : "Maps, common events and troop events"}</p></div>
      <div className="actions"><Button variant="quiet" onClick={guidance}>Guidance & layout</Button><Button disabled={disabled} onClick={files}>Choose files</Button></div></div>
    <div className="translate-file-controls"><label>Find a selected file<input type="search" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} /></label>
      <div className="actions"><span>{matching.length} matching · Page {currentPage + 1} of {lastPage + 1}</span><Button disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>Previous files</Button><Button disabled={currentPage >= lastPage} onClick={() => setPage(currentPage + 1)}>Next files</Button></div></div>
    <table className="translate-files"><thead><tr><th>File</th><th>Planned requests</th><th>Result</th></tr></thead><tbody>
      {matching.slice(currentPage * pageSize, (currentPage + 1) * pageSize).map(file => { const count = estimate?.process?.requests?.filter(request => request.file === file.name).length;
        return <tr key={file.name}><td><strong>{file.name}</strong>{file.title && <small>{file.title}</small>}</td>
          <td>{count == null ? "Estimate needed" : count}</td><td>{edited.has(file.name) ? "Game edited after Apply" : applied.has(file.name) ? "Applied to game" : state.readiness.outputs.includes(file.name) ? "Output saved · Apply needed" : process?.requests?.some(request => request.file === file.name && request.state === "failed") ? "Request failed · Review remaining work" : process?.requests?.some(request => request.file === file.name && request.state === "validated") ? "Partial results saved" : "Ready"}</td></tr>;
      })}
      {!matching.length && <tr><td colSpan={3}>{rows.length ? "No selected files match this search." : "Choose files for this scope."}</td></tr>}
    </tbody></table>
  </div>;
}
