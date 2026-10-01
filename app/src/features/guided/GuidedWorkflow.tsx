import { useState, type ReactNode } from "react";
import { ArrowRight, FolderOpen } from "lucide-react";
import { api } from "../../api/client";
import type { GuidedOptions, GuidedState, Job, GuidedStep, Phase, Preview, Project, TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { flushDrafts } from "../../state/leaveGuards";
import { PageLayout, PageHeader } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { FieldRow } from "../../ui/FieldRow";
import { Button } from "../../ui/Button";
import { Modal } from "../../ui/Modal";
import { Message } from "../../ui/Feedback";
import { JobStatus } from "../../ui/JobStatus";
import ContextEditor from "./ContextEditor";
import RunPanel, { Estimate } from "./RunPanel";
import { FileSelection } from "./FileSelection";
import { EngineOptions } from "./EngineOptions";
import { useGuidedWorkflow } from "./useGuidedWorkflow";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { ActivityHistory, projectActivity } from "./ActivityHistory";

const areas = [{ id: "prepare" as const, label: "Setup" }, { id: "translate" as const, label: "Translate" }, { id: "review" as const, label: "Test & release" }];
const speakers = ["NAMES", "FIRSTLINESPEAKERS", "INLINE401SPEAKERS", "FACENAME101", "AUTONAMEPOPUP101", "SPEAKERS408"];
const advanced = ["CODE122", "CODE122_VAR_RANGES", "CODE357", "CODE355655", "CODE657", "CODE356", "CODE320", "CODE324", "CODE325", "CODE108", "ENABLED_PLUGINS_357", "ENABLED_PATTERNS_355655"];
const actionKey = (name: string, options: Record<string, unknown> = {}) => name === "start" ? `start:${options.mode}` : name;
const jobTime = (job: { updated?: string; created?: string }) => Date.parse(job.updated || job.created || "") || 0;
const fileCount = (count: number) => `${count} ${count === 1 ? "file" : "files"}`;
const phases: [Phase, string][] = [["database", "Names & interface"], ["dialogue", "Dialogue & choices"], ["variables", "Prepare variable references"], ["advanced", "Audited scripts & plugins"]];

export default function GuidedWorkflow({ project, settings, backups, versions }: {
  project: Project; settings: () => void; backups?: ReactNode; versions?: ReactNode;
}) {
  const application = useApplication();
  const state = application.snapshot?.guided;
  const translation = application.snapshot?.translation;
  if (!state || state.projectId !== project.id || !translation || translation.projectId !== project.id)
    return <Message message={application.snapshot?.translationError || "Open this game’s Translation workspace to continue."} />;
  return <Workspace key={project.id} project={project} state={state} translation={translation}
    settings={settings} backups={backups} versions={versions} />;
}

function Workspace({ project, state, translation, settings, backups, versions }: {
  project: Project; state: GuidedState; translation: TranslationState; settings: () => void;
  backups?: ReactNode; versions?: ReactNode;
}) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const draft = useGuidedWorkflow(state, action.report);
  const values = draft.value.values;
  const [preview, setPreview] = useState<Preview | null>(null);
  const [resume, setResume] = useState(false);
  const [started, setStarted] = useState<Record<string, Job>>({});
  const form = useDraft("guided-form:" + project.id, {
    initial: { saved: state.form }, report: action.report,
    persist: (value) => api.guided.form(project.id, value),
  });
  const { version, original, untranslated, only_overflow: onlyOverflow } = form.value || state.form;
  const setVersion = (version: string) => form.session.edit((value) => ({ ...value, version }));
  const setOriginal = (original: string) => form.session.edit((value) => ({ ...value, original }));
  const setUntranslated = (untranslated: boolean) => form.session.edit((value) => ({ ...value, untranslated }));
  const setOnlyOverflow = (only_overflow: boolean) => form.session.edit((value) => ({ ...value, only_overflow }));
  const [reviewed, setReviewed] = useState(false);
  const [playtested, setPlaytested] = useState(false);
  const [output, setOutput] = useState("");
  const area = state.step === "prepare" ? "prepare" : ["apply", "layout", "review"].includes(state.step) ? "review" : "translate";
  const [history, setHistory] = useState(false);
  const [inspected, setInspected] = useState<Job | null>(null);
  const running = !!application.snapshot?.application.running;
  const disabled = action.busy || draft.committing || running;
  const sourceBackup = translation.lifecycle.source_backup;
  const preserved = !!sourceBackup && sourceBackup.available !== false;
  const baseline = preserved && !!translation.git?.configured;
  const edit = <K extends keyof GuidedOptions>(key: K, value: GuidedOptions[K]) =>
    draft.session.edit((current) => ({ ...current, values: { ...current.values, [key]: value } }));
  const save = async () => { await flushDrafts(); if (draft.dirty || state.optionsDraft) await draft.save(); };
  const move = (next: GuidedStep) => action.run(async () => {
    await flushDrafts();
    await api.guided.position(project.id, next);
  });
  const feedback = (key: string, pendingText = "Working…") => ({
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  const operationJob = (name: string, options: Record<string, unknown> = {}): Job | undefined => {
    const key = actionKey(name, options);
    const recorded: Job[] = name === "start"
      ? (state.run && state.run.mode === options.mode ? [state.run] : [])
      : [
          ...state.operations.filter((job) => job.action === name),
          ...translation.jobs.filter((job) => job.kind === "operation" && job.action === name).map((job) => ({
            id: job.id, label: job.label, status: job.status, message: job.message,
            created: job.created, updated: job.updated, log: [],
          })),
        ];
    const acknowledged = started[key];
    if (acknowledged && !recorded.some((job) => job.id === acknowledged.id)) recorded.push(acknowledged);
    return recorded.sort((left, right) => jobTime(right) - jobTime(left))[0];
  };
  const execute = async (value: Preview) => {
    const result = await api.execute(project.id, value.token);
    setStarted((previous) => ({ ...previous, [actionKey(value.action, value.options)]: result }));
    setPreview(null);
  };
  const review = (name: string, options: Record<string, unknown> = {}, files?: string[]) => action.run(async () => {
    await save();
    const result = await api.preview(project.id, name, files, options);
    if (!result.confirmation) await execute(result);
    else setPreview(result);
  }, "", actionKey(name, options));
  const copySkill = (name: string) => action.run(async () => {
    await save();
    await window.dazedtl.copyText((await api.guided.skill(project.id, name)).text);
  }, "Copied. Review the result here when your assistant finishes.", "copy:" + name);
  const copyTask = (name: string, label: string) => <ActionControl label={label} disabled={disabled}
    {...feedback("copy:" + name, "Copying…")} onClick={() => copySkill(name)} />;
  const task = (name: string, label: string, options: Record<string, unknown> = {}, blocked = false,
    variant: "default" | "primary" = "default", files?: string[]) => {
    const recorded = name === "start" && options.mode === "estimate" ? estimate || undefined : operationJob(name, options);
    // The backup's current availability is stronger evidence than an old successful job.
    const job = name === "backup_source" && recorded?.status === "complete" ? undefined : recorded;
    return <ActionControl label={label} disabled={disabled || blocked} variant={variant}
      {...feedback(actionKey(name, options), name === "start" && options.mode === "estimate" ? "Estimating selected files…" : preview ? "Starting…" : "Preparing action…")}
      pending={action.busy && action.key === actionKey(name, options) || !!job && ["ready", "running", "waiting"].includes(job.status)}
      job={job && !["ready", "running", "waiting"].includes(job.status) && (name !== "start" || options.mode === "estimate") ? options.mode === "estimate" && job.status === "complete" ? { ...job, message: "" } : job : undefined} onClick={() => review(name, options, files)} />;
  };
  const job = state.run;
  const unfinished = !!job && ["batch", "translate", "speakers"].includes(job.mode || "") && !["complete", "canceled"].includes(job.status);
  const phaseFiles = state.files.filter((file) => values.selected.includes(file.name) && file.group === (state.phase === "database" ? "database" : "dialogue")).map((file) => file.name);
  const changed = state.sourceStatus.changed;
  const outputFiles = state.readiness.outputs.filter((name) => values.selected.includes(name));
  const layoutFiles = state.files.filter((file) => values.selected.includes(file.name)).map((file) => file.name);
  const applied = outputFiles.length > 0 && outputFiles.every((name) => state.readiness.applied.includes(name));
  const activity = projectActivity(state, translation);
  const activeOperation = activity.find((item) => ["ready", "running", "waiting"].includes(item.status));
  const checkpoint = translation.lifecycle.checkpoint;
  const checkpointCurrent = !!checkpoint && checkpoint.commit === translation.git?.translation_commit && translation.git.worktree_clean;
  const packageReady = baseline && state.readiness.review_current && checkpointCurrent;
  const mode = values.mode === "batch" && !state.provider.batchSupported ? "translate" : values.mode;
  const canPlan = baseline && phaseFiles.length > 0 && !changed.length && !unfinished;
  const estimate = job?.mode === "estimate" && !changed.length && !draft.dirty && !(state.sourceStatus.retired || []).includes(job.id) && job.model === state.provider.model && job.files?.length === phaseFiles.length && job.files.every((name) => phaseFiles.includes(name)) ? job : null;
  const layoutOptions = { files: layoutFiles, widths: values.widths, categories: ["dialogue", "face_dialogue", "list", "notes"], codes: "401,405", max_rows: 4, protect_rows: true, over_limit: onlyOverflow };
  const paid = preview?.action === "start" && preview.options.mode !== "estimate";
  const backupRunning = ["ready", "running"].includes(operationJob("backup_source")?.status || "");
  const assistant = (name: string, title: string, expected: string) => <ActionRow label={<><strong>{title}</strong><small>{expected}</small></>}>
    {copyTask(name, "Copy " + title.toLowerCase() + " task")}
  </ActionRow>;
  const inspect = (job: Job) => {
    setHistory(false);
    setInspected(job);
    void action.run(async () => {
      const saved = await api.guided.inspect(project.id, job.id);
      setInspected((current) => current?.id === job.id ? saved : current);
    }, "", "inspect:" + job.id);
  };
  const qaJob = activity.find((item) => ["qa_prepare", "qa_status"].includes(item.action || "") && item.status === "complete");
  const qaStatus = qaJob?.result?.status && typeof qaJob.result.status === "object" ? qaJob.result.status as Record<string, unknown> : null;
  const qaScreen = qaStatus?.screen as { accepted?: number; total?: number } | undefined;
  const qaDeep = qaStatus?.deep as { accepted?: number; total?: number } | undefined;
  const qaTask = activity.find((item) => item.action === "qa_prepare" && typeof item.result?.handoff === "string");
  const next = !preserved ? "Preserve the original game" : !baseline ? "Prepare the game and review its version baseline" : unfinished ? "Continue the saved run" : changed.length ? "Review changed sources" : outputFiles.length && !applied ? "Review saved outputs and runtime changes" : area === "review" ? state.readiness.review_current ? checkpointCurrent ? "Build the local patch" : "Save a reviewed checkpoint" : "Review and playtest current runtime files" : "Choose a phase and review the run";

  return <PageLayout className="guided-workspace" aria-label="Translation workspace">
    <PageHeader title="Translation" divided description={state.engine === "ACE" ? "RPG Maker VX Ace" : "RPG Maker MV / MZ"}
      actions={<div className="actions"><Button variant="quiet" aria-expanded={history} onClick={() => setHistory(!history)}>Recent activity</Button>
        <Button variant="quiet" onClick={() => action.run(() => window.dazedtl.openFolder("project"))}><FolderOpen size={16} />Game folder</Button></div>} />
    <Tabs id="translation-areas" label="Translation areas" items={areas} value={area} onChange={move} disabled={action.busy} />
    <Message message={action.key ? "" : action.error} onDismiss={action.clear} />
    <Message message={state.collectionError} />
    <div className="guided-next" role="status"><strong>Next: {next}</strong>
      <span className="muted">{baseline ? `Original preserved · Version ${translation.git?.original_version || "baseline"} saved` : "Local preparation comes before paid translation"}</span>
      {area !== "prepare" && !baseline && <Button onClick={() => move("prepare")}>Open setup</Button>}
      {area === "translate" && outputFiles.length > 0 && !applied && <Button onClick={() => move("review")}>Review saved outputs<ArrowRight size={14} /></Button>}
    </div>
    {activeOperation && <Section title="Current operation">
      <JobStatus job={{ ...activeOperation, label: activeOperation.label || "Project operation" }} />
      <ActionControl label="Stop operation" {...feedback("stop-operation", "Stopping…")} disabled={action.busy}
        onClick={() => action.run(async () => { if (state.operations.some((item) => item.id === activeOperation.id)) await api.stop(project.id); else await api.translation.stop(project.id, activeOperation.id); }, "", "stop-operation")} />
    </Section>}
    {job && (unfinished || running && ["running", "waiting"].includes(job.status)) && <RunPanel job={job} active={running && ["running", "waiting"].includes(job.status)} busy={action.busy}
      pendingKey={action.busy ? action.key : ""}
      error={action.key.startsWith("run:") ? action.error : ""}
      stop={() => action.run(() => api.stop(project.id), "", "run:stop")} resume={() => setResume(true)}
      answer={(approved) => action.run(() => api.answer(project.id, job.approval!.token, approved), "", "run:answer:" + approved)}
      exportFiles={() => action.run(async () => setOutput((await api.export(project.id)).path), "", "run:export")} apply={() => move("review")} />}
    {output && <p className="path">Output copy: {output} <Button onClick={() => action.run(() => window.dazedtl.openFolder("output", output))}>Open folder</Button></p>}
    {draft.dirty && <div className="guided-save-bar">
      <span className="muted">Options changed · retained for recovery and saved before preparing a run</span>
      <ActionControl label="Save options" disabled={disabled} {...feedback("save-options", "Saving…")} onClick={() => action.run(save, "Options saved.", "save-options")} />
      <ActionControl label="Discard changes" disabled={disabled} {...feedback("discard-options", "Discarding…")} onClick={() => action.run(draft.discard, "Changes discarded.", "discard-options")} />
    </div>}
    <TabPanel id="translation-areas" value={area}>
    {area === "prepare" && <>
      {baseline && <Section title="Setup complete"><p>Original game preserved and version baseline saved.</p><Button variant="primary" onClick={() => move("translate")}>Choose translation scope<ArrowRight size={15} /></Button></Section>}
      <details className="guided-setup-details" open={!baseline}><summary>{baseline ? "Backup and preparation details" : "Protect and prepare this game"}</summary>
        <Section title="Original game" hint={backupRunning ? "Backing up…" : preserved ? "Preserved" : sourceBackup ? "Backup unavailable" : "Required"}>
          {!preserved && <><p className="muted">Save a recoverable original before changing runtime files.</p>{task("backup_source", sourceBackup ? "Back up current game again" : "Back up original game", {}, false, "primary")}</>}
          {sourceBackup && <div className="guided-backup-location">
            {!preserved && !backupRunning && <Message message={sourceBackup.issue || "The saved backup is unavailable. A replacement saves current files; it cannot recover the deleted original."} />}
            {preserved && <span>{sourceBackup.files.toLocaleString()} files preserved.</span>}
            <span className="path">{sourceBackup.path}</span>
            <ActionControl label="Open backup folder" disabled={!preserved || action.busy} {...feedback("open-backup", "Opening…")}
              onClick={() => action.run(() => window.dazedtl.openFolder("backup", sourceBackup.path), "Backup folder opened.", "open-backup")} />
          </div>}
        </Section>
        {state.engine === "ACE" && <Section title="Extract Ace data">
          <p className="muted">Decrypt the archive if needed, then convert native data to the JSON used by the translation phases.</p>
          {!state.aceAvailable && <p className="muted">Native conversion requires Windows or Wine. Existing ace_json exports can be used.</p>}
          <ActionList><ActionRow label="Encrypted archive">{task("ace_decrypt", "Review archive extraction", {}, !preserved || !state.encrypted.length || !state.aceAvailable)}</ActionRow>
            <ActionRow label="Native data">{task("ace_extract", "Review JSON conversion", {}, !preserved || !state.aceAvailable)}</ActionRow></ActionList>
        </Section>}
        <Section title="Prepare runtime files">
          <p className="muted">Format data before creating the original baseline.</p>
          <ActionList><ActionRow label="Game data">{task("format_data", "Format JSON files", {}, !preserved || !state.files.length)}</ActionRow>
            {state.hasPlugins && <ActionRow label="Plugin configuration">{task("format_plugins", "Format plugins.js", {}, !preserved)}</ActionRow>}</ActionList>
        </Section>
        {!translation.git?.configured && <Section title="Version baseline">
          <fieldset disabled={disabled}>
            <FieldRow id="guided-version" label="Game version">{(props) => <input {...props} value={version} placeholder="1.00" onChange={(event) => setVersion(event.target.value)} />}</FieldRow>
            <FieldRow id="guided-original" label="Matching original" help="For an already translated game, select its matching prepared original.">{(props) => <div className="guided-folder-field"><input {...props} value={original} onChange={(event) => setOriginal(event.target.value)} /><Button onClick={() => action.run(async () => { const folder = await window.dazedtl.chooseFolder(); if (folder) setOriginal(folder); })}>Browse</Button></div>}</FieldRow>
            <label className="toggle"><input type="checkbox" checked={untranslated} onChange={(event) => setUntranslated(event.target.checked)} />This game is untranslated; use it as the original baseline.</label>
          </fieldset>
          {task("git_setup", "Review version baseline", { version, original, untranslated }, !preserved || !version.trim() || (!original && !untranslated), "primary")}
          <p className="muted">Review the runtime scope before creating original and translation branches.</p>
        </Section>}
      </details>
      <details><summary>Optional GameUpdate support</summary><p className="muted">Install updater files when this patch should support GameUpdate. Review the patch scope again if you add runtime files later.</p>{task("gameupdate", "Create GameUpdate files", {}, !preserved)}</details>
      {backups && <details><summary>Backups and recovery</summary>{backups}</details>}
      {versions && <details><summary>Source versions and official updates</summary>{versions}</details>}
    </>}

    {area === "translate" && <>
      {changed.length > 0 && <Section title="Source changes need review"><p>{changed.join(", ")}</p><p className="muted">Existing results and runs stay saved. Refreshing these sources archives their working copies and outputs, then starts a new pass from the source baseline.</p>
        {task("refresh_sources", "Review source refresh", {}, unfinished || !baseline, "primary", changed)}
        <Button variant="quiet" onClick={() => move("prepare")}>Source versions and recovery</Button>
      </Section>}
      <Section title={unfinished ? "New run settings" : "Prepare a translation run"} hint={`${fileCount(phaseFiles.length)} in this phase`}>
        <FieldRow id="guided-phase" label="Phase">{(props) => <select {...props} disabled={disabled} value={state.phase === "speakers" ? "database" : state.phase}
          onChange={(event) => { const phase = event.target.value as Phase; void action.run(async () => { await save(); await api.phase(project.id, phase); }); }}>
          {phases.map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select>}</FieldRow>
        <FieldRow id="guided-mode" label="API mode">{(props) => <select {...props} disabled={disabled} value={mode} onChange={(event) => edit("mode", event.target.value as GuidedOptions["mode"])}>
          <option value="batch" disabled={!state.provider.batchSupported}>Batch{state.provider.batchSupported ? " (recommended)" : " (unavailable)"}</option><option value="translate">Live API</option></select>}</FieldRow>
        <div className="guided-model"><span className="muted">{state.provider.model || "Choose a model to estimate or translate"}</span><Button variant="quiet" onClick={settings}>Connection and model</Button></div>
        {!phaseFiles.length && <p className="muted">Select {state.phase === "database" ? "database" : "event or map"} files below, or choose another phase.</p>}
        {baseline && !state.provider.ready && <p className="muted">Configure the connection in Settings before paid translation. Local cost estimates need a selected model.</p>}
        {unfinished && <p className="muted">Finish or resume the saved run before preparing another phase or estimate. Its files and settings stay frozen.</p>}
        <ActionList><ActionRow label={!state.provider.enabled ? "Provider execution is disabled for this launch. Local estimates are available." : mode === "batch" ? "Prepare the selected scope; approve the collected quote before submission." : "Review selected files and saved settings before starting paid requests."}>
          {task("start", mode === "batch" ? "Review Batch run" : "Review Live API run", { mode }, !canPlan || !state.provider.ready || !state.provider.enabled, "primary")}</ActionRow>
          <ActionRow label="Optional local estimate. No translation is submitted.">{task("start", "Estimate cost", { mode: "estimate" }, !canPlan || !state.provider.model)}</ActionRow></ActionList>
        {estimate && <div className="guided-estimate-result">
          {estimate.status === "complete" && estimate.estimate && <><p>Last estimate for {fileCount(estimate.files?.length || 0)} using its saved settings.</p><Estimate value={estimate.estimate} /></>}
          {!['running', 'waiting'].includes(estimate.status) && <Button variant="quiet" onClick={() => inspect(estimate)}>Inspect last estimate</Button>}
        </div>}
      </Section>
      <Section title="Translation scope" hint={state.engine === "ACE" ? "Converted Ace JSON" : "Supported RPG Maker JSON"}>
        <FileSelection state={state} selected={values.selected} disabled={disabled} change={(names) => edit("selected", names)} />
        <p className="muted">Selected files in the current phase become the run’s frozen scope. Working copies are prepared automatically; saved phase results carry forward.</p>
      </Section>
      <details open={state.step === "context"}><summary>Game context and glossary</summary>
        <p className="muted">Prepare and save names, terminology, and game instructions before translating dialogue. This guidance is shared by every phase.</p>
        <ActionList><ActionRow label="Detect speakers from selected event files; name translation requests require approval.">
          {task("start", "Review speaker collection", { mode: "speakers" }, !baseline || unfinished || !state.files.some((file) => file.group === "dialogue" && values.selected.includes(file.name)) || !state.provider.ready || !state.provider.enabled)}</ActionRow>
          {assistant("setup", "Context setup", "Paste into your coding assistant, then review the saved glossary and game instructions here.")}</ActionList>
        <details><summary>Speaker detection options</summary><EngineOptions state={state} values={values.engine_options} keys={speakers} disabled={disabled} change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} /></details>
        <ContextEditor projectId={project.id} documents={state.documents} recovered={state.drafts} disabled={disabled} />
      </details>
      <details><summary>Phase order and advanced options</summary>
        <p className="muted">Names & interface → dialogue & choices → variable references → audited scripts & plugins. Review an early scene before expanding the scope.</p>
        {(state.phase === "advanced" || state.phase === "variables") && <>
          <ActionList>{assistant("advanced", "Advanced-text audit", "Review player-visible script, variable, and plugin fields. Enable only the fields supported by the audit.")}</ActionList>
          <EngineOptions state={state} values={values.engine_options} keys={advanced} disabled={disabled} change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} />
        </>}
        {state.phase === "dialogue" && <label className="toggle"><input type="checkbox" checked={values.phase1_comments} disabled={disabled} onChange={(event) => edit("phase1_comments", event.target.checked)} />Include comment continuations (408) displayed by this game.</label>}
        <EngineOptions state={state} values={values.engine_options} keys={["IGNORETLTEXT", "PRESERVEORIGINAL", "FIXTEXTWRAP", "BRFLAG", "TLSYSTEMVARIABLES", "TLSYSTEMSWITCHES"]} disabled={disabled} change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} />
        {task("refresh_sources", "Review refresh of selected sources", {}, !baseline || unfinished || !values.selected.length, "default", values.selected)}
      </details>
    </>}

    {area === "review" && <>
      <Section title="Readiness for this scope">
        <dl className="guided-readiness">
          <div><dt>Saved outputs</dt><dd>{outputFiles.length ? `${fileCount(outputFiles.length)} selected and available` : "No selected outputs available"}</dd></div>
          <div><dt>Applied to game</dt><dd>{applied ? state.readiness.runtime_edited.some((name) => outputFiles.includes(name)) ? "Applied · later runtime edits need review" : "Matches saved outputs" : outputFiles.length ? "Review outputs and runtime changes" : "Waiting for translation"}</dd></div>
          <div><dt>Playtest review</dt><dd>{state.readiness.review_current ? "Recorded for current runtime files" : translation.lifecycle.guided_review ? "Files changed; review again" : "Not recorded"}</dd></div>
          <div><dt>Checkpoint</dt><dd>{checkpointCurrent ? "Current version saved" : checkpoint ? "Save current changes" : "Not saved"}</dd></div>
        </dl>
      </Section>
      {changed.length > 0 && <Section title="Source changes need review"><p className="muted">Review and refresh changed sources in Translate before applying older outputs.</p><Button onClick={() => move("translate")}>Review changed sources</Button></Section>}
      <Section title="Apply saved outputs" hint={`${fileCount(outputFiles.length)} selected`}>
        {task("export_selected", "Review files to apply", {}, !baseline || !outputFiles.length || !!changed.length, "primary")}
        {state.engine === "ACE" && <><p className="muted">Pack the latest JSON into native data before each playtest, including after layout or QA changes.</p>{task("ace_pack", "Review native Ace packing", {}, !baseline || !state.aceAvailable || !state.files.length)}</>}
      </Section>
      <details open={state.step === "layout"}><summary>Text fitting</summary>
        <p className="muted">Measure the game’s text widths, scan applied outputs, then review changes. Protected controls and original text stay intact.</p>
        <fieldset disabled={disabled}>
          {([['width', 'Dialogue'], ['faceWidth', 'Face dialogue'], ['listWidth', 'List / help'], ['noteWidth', 'Notes']] as const).map(([key, label]) => <FieldRow key={key} id={"guided-width-" + key} label={label}>{(props) => <input {...props} type="number" min={20} max={300} value={values.widths[key]} onChange={(event) => edit("widths", { ...values.widths, [key]: Number(event.target.value) })} />}</FieldRow>)}
          <label className="toggle"><input type="checkbox" checked={onlyOverflow} onChange={(event) => setOnlyOverflow(event.target.checked)} />Only rewrap text over its width limit</label>
        </fieldset>
        <ActionList>{assistant("wrap", "Width measurement", "Return with measured widths for the game’s actual font and renderer.")}
          <ActionRow label="Scan selected runtime files after applying translations or completing external edits.">{task("rewrap_preview", "Scan text fitting", layoutOptions, !baseline || !layoutFiles.length)}</ActionRow>
          <ActionRow label="Requires a completed scan matching these files and options.">{task("rewrap_apply", "Review rewrap changes", layoutOptions, !baseline || !layoutFiles.length || !state.readiness.layout_scan || draft.dirty)}</ActionRow></ActionList>
      </details>
      <details><summary>Assistant tasks and text QA</summary>
        <p className="muted">Copy instructions into your coding assistant. The app reports saved QA findings; copying instructions does not start or complete the assistant’s work.</p>
        <ActionList>{assistant("plugins", state.engine === "ACE" ? "Ruby text review" : "Plugin text review", "Return with player-visible text findings and corrections for review.")}
          <ActionRow label="Prepare or reopen the saved text-QA task.">{task("qa_prepare", "Prepare text QA task", { focus: "release" }, !baseline)}</ActionRow>
          <ActionRow label="Read saved reports after the assistant finishes.">{task("qa_status", "Refresh QA findings", { focus: "release" }, !baseline)}</ActionRow>
          {qaTask && <ActionRow label="Continue the prepared QA task in your coding assistant."><ActionControl label="Copy prepared QA task" disabled={action.busy} {...feedback("copy:qa", "Copying…")} onClick={() => action.run(() => window.dazedtl.copyText(String(qaTask.result!.handoff)), "QA instructions copied. Review saved findings after the assistant finishes.", "copy:qa")} /></ActionRow>}
          {assistant("walkthrough", "Playtest", "Return with runtime findings, text-layout checks, and any unresolved or excluded scope.")}</ActionList>
        {qaStatus && <div className="guided-qa-status"><strong>Last reported QA stage: {String(qaStatus.stage || "Task prepared").replaceAll("_", " ")}</strong>
          {qaScreen && <p>Screen review: {qaScreen.accepted || 0} / {qaScreen.total || 0}</p>}{qaDeep && <p>Deep review: {qaDeep.accepted || 0} / {qaDeep.total || 0}</p>}
          {typeof qaStatus.findings_file === "string" && qaStatus.findings_file && <p className="path">Reported findings: {qaStatus.findings_file}</p>}
        </div>}
      </details>
      <Section title="Playtest and record review">
        {state.engine === "MVMZ" && task("playtest_install", "Review playtest tool installation", {}, !baseline)}
        <p className="muted">Check runtime text, layout, and image text. Resolve or document exclusions. This attestation is separate from the assistant’s QA report.</p>
        <fieldset disabled={disabled}>
          <label className="toggle"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />I reviewed this scope and resolved or documented exclusions, including image text.</label>
          <label className="toggle"><input type="checkbox" checked={playtested} onChange={(event) => setPlaytested(event.target.checked)} />I playtested the current files and checked text layout.{state.engine === "ACE" ? " The latest JSON is packed into native data." : ""}</label>
        </fieldset>
        {task("guided_review", "Record review of current files", { reviewed, playtested }, !baseline || !reviewed || !playtested)}
      </Section>
      <Section title="Local patch">
        <ActionList><ActionRow label="Save reviewed runtime files and a workspace restore point.">{task("checkpoint", "Review checkpoint", {}, !baseline || !state.readiness.review_current)}</ActionRow>
          <ActionRow label={packageReady ? "Current review and checkpoint are ready for packaging." : "Requires a review of current files and a matching saved checkpoint."}>{task("guided_package", "Build local patch ZIP", {}, !packageReady, "primary")}</ActionRow></ActionList>
        {translation.lifecycle.delivery && (state.readiness.delivery_available ? <p className="path">Saved patch: {translation.lifecycle.delivery.path}</p> : <p className="muted">The previously saved patch is unavailable.</p>)}
        <p className="muted">Changes after review require another review. Publishing is a separate action.</p>
      </Section>
    </>}
    </TabPanel>
    {history && <Modal label="Recent activity" onDismiss={() => setHistory(false)}><h2>Recent activity</h2><ActivityHistory state={state} translation={translation} inspect={inspect} /><Button onClick={() => setHistory(false)}>Close</Button></Modal>}
    {inspected && <Modal label="Activity details" onDismiss={() => setInspected(null)}><h2>{inspected.label || (inspected.mode === "estimate" ? "Cost estimate" : "Saved translation run")}</h2>
      <JobStatus job={{ ...inspected, label: inspected.label || (inspected.mode === "estimate" ? "Cost estimate" : "Translation run") }} />
      {inspected.files && <><p>{fileCount(inspected.files.length)} frozen · {inspected.model} · {inspected.mode}</p><ul>{inspected.files.map((name) => <li key={name}>{name}</li>)}</ul></>}
      {action.busy && action.key === "inspect:" + inspected.id && <p role="status">Loading saved activity details…</p>}
      <Message message={action.key === "inspect:" + inspected.id ? action.error : ""} />
      {inspected.status === "complete" && Object.keys(inspected.outputs || {}).length > 0 && <><ActionControl label="Save this run’s output copy" disabled={action.busy || inspected.outputsAvailable === false} {...feedback("run:export", "Saving output copy…")} onClick={() => action.run(async () => setOutput((await api.export(project.id, inspected.id)).path), "Output copy saved.", "run:export")} />{inspected.outputsAvailable === false && <p className="muted">The saved run’s output files are unavailable.</p>}</>}
      {inspected.result && <details><summary>Diagnostic result</summary><pre>{JSON.stringify(inspected.result, null, 2)}</pre></details>}
      {!!inspected.log.length && <details><summary>Diagnostic log</summary><pre>{inspected.log.join("\n")}</pre></details>}
      <Button onClick={() => setInspected(null)}>Close</Button></Modal>}
    {preview && <Modal label="Review translation action" dismissible={!action.busy} onDismiss={() => setPreview(null)}>
      <h2>{preview.label}</h2><p className="path">{preview.destination}</p>
      {!!preview.paths.length && <><p>{fileCount(preview.paths.length)} in this action</p><ul>{preview.paths.map((name) => <li key={name}>{name}</li>)}</ul></>}
      {!!preview.additions?.length && <details><summary>{preview.additions.length} files absent from the original baseline</summary><ul>{preview.additions.map((name) => <li key={name}>{name}</li>)}</ul></details>}
      {preview.action === "git_setup" && <p>Version {String(preview.options.version)} · {preview.options.untranslated ? "Use the selected untranslated game as the original." : "Matching original: " + String(preview.options.original)}</p>}
      {preview.action === "backup_source" && sourceBackup?.available === false && <p>This saves current files. It cannot recover the deleted original.</p>}
      {preview.action === "refresh_sources" && <p>Archive these files’ working copies, accumulated outputs, and variable cache before refreshing from original source. Saved provider runs remain attached and unchanged.</p>}
      {preview.action === "export_selected" && <p>Replace these runtime files with the accumulated translated outputs.</p>}
      {paid && <p>{state.provider.model} · {preview.options.mode === "batch" ? "Prepare the selected scope for a separate Batch cost approval. Speaker translation may request its own approval." : "API requests may incur charges using the settings frozen with this run."}</p>}
      {preview.action === "guided_review" && <p>Record your review and playtest for the exact current files.</p>}
      {preview.rewrap && <><p>{preview.rewrap.changes_found} changes · {preview.rewrap.overflow_skipped} protected overflows skipped</p>{preview.rewrap.previews.map((row, index) => <details key={index}><summary>{row.file_name} · {row.locator}</summary><strong>Before</strong><pre>{row.before}</pre><strong>After</strong><pre>{row.after}</pre></details>)}</>}
      <Message message={action.error} />
      <div className="actions"><Button disabled={action.busy} onClick={() => setPreview(null)}>Cancel</Button><Button variant="primary" pending={action.busy} onClick={() => action.run(() => execute(preview), "", actionKey(preview.action, preview.options))}>{paid && preview.options.mode === "translate" ? "Approve and start Live API" : paid && preview.options.mode === "batch" ? "Prepare Batch for cost review" : preview.action === "refresh_sources" ? "Archive and refresh sources" : "Run this action"}</Button></div>
    </Modal>}
    {resume && <Modal label="Resume saved run" dismissible={!action.busy} onDismiss={() => setResume(false)}>
      <h2>Resume saved run?</h2><p>Continue its frozen files, context, and provider settings. Remaining requests may incur charges.</p><Message message={action.error} />
      <div className="actions"><Button disabled={action.busy} onClick={() => setResume(false)}>Cancel</Button><Button variant="primary" pending={action.busy} onClick={() => action.run(async () => { await api.resume(project.id); setResume(false); }, "", "run:resume")}>Resume saved run</Button></div>
    </Modal>}
  </PageLayout>;
}
