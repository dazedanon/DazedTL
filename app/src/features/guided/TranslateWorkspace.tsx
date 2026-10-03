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
  const process = run?.process;
  const quote = estimate?.estimate;
  const cost = quote && Number(mode === "batch" ? quote.batch_nocache_cost ?? quote.batch_cost : quote.live_cost);
  const active = !!run && ["running", "waiting"].includes(run.status);
  const errors = process?.errors || [];
  const details = estimate || run;
  const status = pending ? "Preparing a local estimate…" : active ? run.message : run?.status === "complete" ? "Saved translation finished" : "Ready for translation";
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
      <div><dt>Verified files</dt><dd>{rows.filter(file => state.readiness.outputs.includes(file.name)).length} <small>/ {rows.length}</small></dd></div>
      <div><dt>Planned requests</dt><dd>{estimate?.process?.prepared ?? "-"}</dd></div>
      <div><dt>Provider work</dt><dd>{active ? run.approval ? "Awaiting approval" : "In progress" : process?.uncertain ? "Needs reconciliation" : process?.failed ? "Requests rejected" : process?.submitted ? "Finished" : "Not submitted"}</dd></div>
      <div><dt>Local estimate</dt><dd>{Number.isFinite(cost) ? "$" + cost!.toFixed(4) : "Not calculated"}</dd></div>
    </dl>
    <div className="translate-status"><div><strong>{status}</strong><p>{active ? run.message : "Translate prepares remaining work with current settings, then opens cost review."}</p>
      {active && run.progress && <progress max={run.progress.total || 1} value={run.progress.current} />}
    </div>{details && <Button disabled={disabled} onClick={() => requests(details)}>View requests</Button>}</div>
    {!!errors.length && <div className="translate-run-error" role="status"><strong>{process?.failed || "Saved"} {process?.failed ? "requests rejected" : "run needs attention"}</strong>
      <p>{errors.slice(0, 2).join(" · ")}</p><small>History and verified results are retained automatically.</small></div>}
    <div className="translate-files-heading"><div><h3>Selected files</h3><p>{rows.length} files · {scope === "database" ? "Names, descriptions and interface terms" : "Maps, common events and troop events"}</p></div>
      <div className="actions"><Button variant="quiet" onClick={guidance}>Guidance & layout</Button><Button disabled={disabled} onClick={files}>Choose files</Button></div></div>
    <table className="translate-files"><thead><tr><th>File</th><th>Planned requests</th><th>Result</th></tr></thead><tbody>
      {rows.map(file => { const count = estimate?.process?.requests?.filter(request => request.file === file.name).length;
        return <tr key={file.name}><td><strong>{file.name}</strong>{file.title && <small>{file.title}</small>}</td>
          <td>{count == null ? "Estimate needed" : count}</td><td>{state.readiness.outputs.includes(file.name) ? "Verified output saved" : process?.requests?.some(request => request.file === file.name && request.state === "validated") ? "Partial results saved" : "Ready"}</td></tr>;
      })}
      {!rows.length && <tr><td colSpan={3}>Choose files for this scope.</td></tr>}
    </tbody></table>
  </div>;
}
