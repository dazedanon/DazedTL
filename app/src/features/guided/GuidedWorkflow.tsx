import { useEffect, useRef, useState, type ReactNode } from "react";
import { FolderOpen } from "lucide-react";
import { api } from "../../api/client";
import type { GuidedForm, GuidedOptions, GuidedState, GuidedStep, Job, Phase, Preview, Project, TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { flushDrafts } from "../../state/leaveGuards";
import { PageBody, PageHeader, PageLayout } from "../../ui/PageLayout";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { DocumentEditor } from "../../ui/DocumentEditor";
import { FieldRow } from "../../ui/FieldRow";
import { Message } from "../../ui/Feedback";
import { JobStatus } from "../../ui/JobStatus";
import { Modal } from "../../ui/Modal";
import { Section } from "../../ui/Section";
import { VirtualList } from "../../ui/VirtualList";
import { ActivityHistory, projectActivity } from "./ActivityHistory";
import { EngineOptions } from "./EngineOptions";
import { FileSelection } from "./FileSelection";
import RunPanel, { Estimate } from "./RunPanel";
import { useContextDraft } from "./useContextDraft";
import { useGuidedWorkflow } from "./useGuidedWorkflow";
import { initialPosition, runPhase, runStage, stagesFor, unfinishedRun } from "./workflow";
import { WorkflowNavigation } from "./WorkflowNavigation";
import { SpeakerFindings } from "./SpeakerFindings";

const speakers = ["NAMES", "FIRSTLINESPEAKERS", "INLINE401SPEAKERS", "FACENAME101", "AUTONAMEPOPUP101", "SPEAKERS408"];
const advanced = ["CODE122", "CODE122_VAR_RANGES", "CODE357", "ENABLED_PLUGINS_357", "CODE355655", "ENABLED_PATTERNS_355655", "CODE657", "CODE356", "CODE320", "CODE324", "CODE325", "CODE108"];
const advancedCodes = advanced.filter((key) => key.startsWith("CODE") && key !== "CODE122_VAR_RANGES");
const phaseLabels: Record<Phase, string> = { database: "Database & interface", dialogue: "Dialogue & choices", variables: "Variable comparison cache", advanced: "Audited extra text", speakers: "Optional name translation" };
const actionKey = (name: string, options: Record<string, unknown> = {}) => name === "start" ? `start:${options.mode}:${options.phase || "speakers"}` : name;
const jobTime = (job: { updated?: string; created?: string }) => Date.parse(job.updated || job.created || "") || 0;
const fileCount = (count: number) => `${count} ${count === 1 ? "file" : "files"}`;
const pathKey = (name: string) => name;
type Panel = "tasks" | "files" | "backups" | "versions" | "speakers" | "widths" | "options" | "tools" | "project-tools" | "references" | "preparation" | "exclusions" | null;
type Props = { project: Project; settings: () => void; backups?: (target: HTMLElement | null) => ReactNode;
  versions?: (actions: { backups: () => void; prepare: () => void; checkpoint: () => void; target: HTMLElement | null }) => ReactNode };

export default function GuidedWorkflow(props: Props) {
  const { snapshot } = useApplication();
  const state = snapshot?.guided, translation = snapshot?.translation;
  if (!state || state.projectId !== props.project.id || !translation || translation.projectId !== props.project.id)
    return <Message message={snapshot?.translationError || "Open this game’s Translation workspace to continue."} />;
  return <Workspace key={props.project.id} {...props} state={state} translation={translation} />;
}

function Workspace({ project, state, translation, settings, backups, versions }: Props & { state: GuidedState; translation: TranslationState }) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const speakerAction = useAction({ after: application.refresh });
  const draft = useGuidedWorkflow(state, action.report);
  const context = useContextDraft(project.id, state.drafts, action.report);
  const form = useDraft("guided-form:" + project.id, { initial: { saved: state.form }, report: action.report, persist: (value) => api.guided.form(project.id, value) });
  const values = draft.value.values, fields = form.value || state.form;
  const stages = stagesFor(state.engine);
  const position = initialPosition(state, translation);
  const stage = stages.find((item) => item.id === position.step)!;
  const selectedTask = stage.tasks.find((item) => item.id === position.task);
  const taskId = selectedTask?.id || "run";
  const taskIndex = stage.tasks.findIndex((item) => item.id === taskId);
  const [panel, setPanel] = useState<Panel>(null);
  const [utilityActions, setUtilityActions] = useState<HTMLDivElement | null>(null);
  const [fileBaseline, setFileBaseline] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [resume, setResume] = useState(false);
  const [history, setHistory] = useState(false);
  const [inspected, setInspected] = useState<Job | null>(null);
  const [started, setStarted] = useState<Record<string, Job>>({});
  const [estimateScope, setEstimateScope] = useState<{ id: string; phase: Phase } | null>(null);
  const [documentName, setDocumentName] = useState("quirks");
  const [output, setOutput] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { bodyRef.current?.scrollTo(0, 0); headingRef.current?.focus({ preventScroll: true }); }, [taskId, position.step]);
  const running = !!application.snapshot?.application.running;
  const disabled = action.busy || speakerAction.busy || draft.committing || context.committing || running;
  const sourceBackup = translation.lifecycle.source_backup;
  const preserved = !!sourceBackup && sourceBackup.available !== false;
  const baseline = preserved && !!translation.git?.configured;
  const job = state.run, unfinished = unfinishedRun(state);
  const findings = state.speakerSetup;
  const speakersConfigured = findings.status === "applied";
  const scan = state.speakerScan;
  const changed = state.sourceStatus.changed;
  const selectedFiles = new Set(values.selected);
  const eventFiles = state.files.filter((file) => file.group === "dialogue" && selectedFiles.has(file.name));
  const databaseFiles = state.files.filter((file) => file.group === "database" && selectedFiles.has(file.name));
  const outputFiles = state.readiness.outputs.filter((name) => selectedFiles.has(name));
  const applied = outputFiles.length > 0 && outputFiles.every((name) => state.readiness.applied.includes(name));
  const layoutFiles = state.files.filter((file) => selectedFiles.has(file.name)).map((file) => file.name);
  const enabledCodes = advancedCodes.filter((key) => values.engine_options[key] === true);
  const advancedReady = enabledCodes.length > 0 && (values.engine_options.CODE122 !== true || String(values.engine_options.CODE122_VAR_RANGES || "").trim().length > 0);
  const mode = values.mode === "batch" && !state.provider.batchSupported ? "translate" : values.mode;
  const phase: Phase = taskId === "advanced-run" ? "advanced" : taskId === "dialogue" ? "dialogue" : taskId === "variables" ? "variables" : "database";
  const phaseFiles = phase === "database" ? databaseFiles : eventFiles;
  const estimate = job?.mode === "estimate" && job.id === estimateScope?.id && phase === estimateScope.phase && !changed.length && !draft.dirty && !(state.sourceStatus.retired || []).includes(job.id) && job.model === state.provider.model && job.files?.length === phaseFiles.length && job.files.every((name) => phaseFiles.some((file) => file.name === name)) ? job : null;
  const activity = projectActivity(state, translation);
  const activeOperation = activity.find((item) => ["ready", "running", "waiting"].includes(item.status));
  const qaTask = activity.find((item) => item.action === "qa_prepare" && typeof item.result?.handoff === "string");
  const qaJob = activity.find((item) => ["qa_prepare", "qa_status"].includes(item.action || "") && item.status === "complete");
  const qaStatus = qaJob?.result?.status && typeof qaJob.result.status === "object" ? qaJob.result.status as Record<string, unknown> : null;
  const release = fields.release;
  const releaseAction = release.kind === "game" ? "release" : "release_patch";
  const releasePath = release.directory.replace(/[\\/]+$/, "") + "/" + release.name;
  const artifact = state.artifacts.find((item) => item.kind === release.kind);
  const currentArtifact = artifact?.path.replaceAll("\\", "/") === releasePath.replaceAll("\\", "/");
  const feedbackKeys = new Set<string>();

  const edit = <K extends keyof GuidedOptions>(key: K, value: GuidedOptions[K]) => draft.session.edit((current) => ({ ...current, values: { ...current.values, [key]: value } }));
  const editForm = <K extends keyof GuidedForm>(key: K, value: GuidedForm[K]) => form.session.edit((current) => ({ ...current, [key]: value }));
  const editRelease = <K extends keyof GuidedForm["release"]>(key: K, value: GuidedForm["release"][K]) => form.session.edit((current) => ({ ...current, release: { ...current.release, [key]: value } }));
  const save = async () => { await flushDrafts(); if (draft.dirty || state.optionsDraft) await draft.save(); };
  const navigate = async (step: GuidedStep, task: string) => { await flushDrafts(); await api.guided.position(project.id, step, task); };
  const move = (step: GuidedStep, task: string) => action.run(async () => { await navigate(step, task); setPanel(null); }, "", "position");
  const stepTask = (task: string) => { const owner = stages.find((item) => item.tasks.some((entry) => entry.id === task)); if (owner) void move(owner.id, task); };
  const next = () => {
    if (taskIndex < 0) return stage.tasks[0];
    return stage.tasks[taskIndex + 1] || stages[stages.indexOf(stage) + 1]?.tasks[0];
  };
  const advance = (label?: string, target = next(), variant: "primary" | "quiet" = "primary") => target && <Button variant={variant} disabled={action.busy || draft.committing || context.committing} onClick={() => stepTask(target.id)}>{label || "Continue to " + target.title.toLowerCase()}</Button>;
  const feedback = (key: string, pendingText = "Working…") => {
    feedbackKeys.add(key);
    return { pending: action.busy && action.key === key, pendingText, error: action.key === key ? action.error : "", notice: action.key === key ? action.notice : "" };
  };
  const operationJob = (name: string, options: Record<string, unknown> = {}): Job | undefined => {
    const recorded: Job[] = name === "start" ? state.run && state.run.mode === options.mode ? [state.run] : [] : [
      ...state.operations.filter((item) => item.action === name),
      ...translation.jobs.filter((item) => item.kind === "operation" && item.action === name).map((item) => ({ id: item.id, action: item.action || undefined, label: item.label, status: item.status, message: item.message, created: item.created, updated: item.updated, result: item.result, log: [] })),
    ];
    const acknowledged = started[actionKey(name, options)];
    if (acknowledged && !recorded.some((item) => item.id === acknowledged.id)) recorded.push(acknowledged);
    return recorded.sort((a, b) => jobTime(b) - jobTime(a))[0];
  };
  const execute = async (value: Preview) => {
    const result = await api.execute(project.id, value.token);
    setStarted((previous) => ({ ...previous, [actionKey(value.action, value.options)]: result }));
    setPreview(null);
    if (value.action === "start") {
      if (value.options.mode === "estimate") setEstimateScope({ id: result.id, phase: value.options.phase as Phase });
      else await navigate(value.options.mode === "speakers" ? "context" : value.options.phase === "advanced" ? "advanced" : "translate", "run");
    }
  };
  const review = (name: string, options: Record<string, unknown> = {}, files?: string[], inspectOnly = false) => action.run(async () => {
    await save();
    const { phase, ...requestOptions } = options;
    if (name === "start" && phase) await api.phase(project.id, phase as Phase);
    const result = await api.preview(project.id, name, files, requestOptions);
    if (!result.confirmation && !inspectOnly) await execute(result); else setPreview(result);
  }, "", actionKey(name, options));
  const task = (name: string, label: string, options: Record<string, unknown> = {}, blocked = false, variant: "default" | "primary" = "default", files?: string[]) => {
    const recorded = name === "start" ? options.mode === "estimate" ? estimate || undefined : undefined : operationJob(name, options);
    const current = name === "backup_source" && recorded?.status === "complete" ? undefined : recorded;
    const active = current && ["ready", "running", "waiting"].includes(current.status);
    return <ActionControl label={label} disabled={disabled || blocked} variant={variant}
      {...feedback(actionKey(name, options), active ? current.message || "Working…" : name === "start" && options.mode === "estimate" ? "Estimating selected files…" : "Preparing action…")}
      pending={action.busy && action.key === actionKey(name, options) || !!active}
      job={current && !active ? options.mode === "estimate" && current.status === "complete" ? { ...current, message: "" } : current : undefined}
      onClick={() => review(name, options, files)} />;
  };
  const copyTask = (name: string, label: string, variant: "default" | "primary" | "quiet" = "default") => <ActionControl label={label} variant={variant} disabled={disabled} {...feedback("copy:" + name, "Copying…")}
    onClick={() => action.run(async () => { await save(); await window.dazedtl.copyText((await api.guided.skill(project.id, name)).text); }, "Task copied. Return to its saved results when your assistant finishes.", "copy:" + name)} />;
  const inspect = (item: Job) => {
    setHistory(false); setInspected(item);
    void action.run(async () => { const saved = await api.guided.inspect(project.id, item.id); setInspected((current) => current?.id === item.id ? saved : current); }, "", "inspect:" + item.id);
  };
  const chooseFiles = () => { setFileBaseline([...values.selected]); setPanel("files"); };
  const closePanel = () => panel === "files" ? action.run(async () => { edit("selected", fileBaseline); await flushDrafts(); setPanel(null); }, "", "files:cancel") : setPanel(null);
  const chooseFolder = (key: "original" | "release") => action.run(async () => {
    const folder = await window.dazedtl.chooseFolder();
    if (folder) key === "original" ? editForm("original", folder) : editRelease("directory", folder);
  }, "", "folder:" + key);
  const saveDocuments = (names: string[], target = next()) => action.run(async () => {
    for (const name of names) await context.save(name);
    if (target) { const owner = stages.find((item) => item.tasks.some((entry) => entry.id === target.id))!; await navigate(owner.id, target.id); }
  }, "Guidance saved.", "context:save");
  const layoutOptions = { files: layoutFiles, widths: values.widths, categories: ["dialogue", "face_dialogue", "list", "notes"], codes: "401,405", max_rows: 4, protect_rows: true, over_limit: fields.only_overflow };
  const widths = <fieldset disabled={disabled} className="guided-widths">{([["width", "Dialogue"], ["faceWidth", "With portrait"], ["listWidth", "List / help"], ["noteWidth", "Notes"]] as const).map(([key, label]) =>
    <label key={key}>{label}<input aria-label={label + " width in characters"} type="number" min={20} max={key === "faceWidth" ? values.widths.width : 300} value={values.widths[key]}
      onChange={(event) => edit("widths", { ...values.widths, [key]: Number(event.target.value) })} /></label>)}</fieldset>;
  const fileSummary = (count = values.selected.length) => <ActionList><ActionRow label={<><strong>{fileCount(count)} selected</strong><small>Selections remain checked when you filter, switch phases, or return later.</small></>}><Button disabled={disabled} onClick={chooseFiles}>Choose files</Button></ActionRow></ActionList>;
  const connection = <div className="guided-connection"><div><span>{state.provider.model || "No model selected"}</span><Button variant="quiet" onClick={settings}>Connection & model</Button></div><div className="guided-mode" role="group" aria-label="Translation mode">
    <Button aria-pressed={mode === "translate"} disabled={disabled} onClick={() => edit("mode", "translate")}>Live API</Button>
    {state.provider.batchSupported && <Button aria-pressed={mode === "batch"} disabled={disabled} onClick={() => edit("mode", "batch")}>Batch API</Button>}
    </div>{!state.provider.ready && <p className="muted">Configure a connection before paid translation.</p>}{!state.provider.enabled && <p className="muted">Provider execution is disabled for this launch. Local estimates are available.</p>}</div>;
  const savedNames = taskId === "glossary" ? ["glossary"] : ["quirks", "game", ...[...new Set([...Object.keys(state.documents), ...Object.keys(context.drafts)])].filter((name) => name.startsWith("custom:"))];
  const formatActions = [{ id: "format_data", title: "Format game data", hint: "Prepare the JSON used by the translation phases." },
    ...(state.hasPlugins ? [{ id: "format_plugins", title: "Format plugins.js", hint: "Prepare the game’s plugin configuration." }] : []),
    { id: "gameupdate", title: "Create GameUpdate files", hint: "Add player patch support." }];
  const nextPreparation = formatActions.find((item) => operationJob(item.id)?.status !== "complete");
  const completed = new Set<string>([...(preserved ? ["backup"] : []), ...(baseline ? ["baseline"] : []), ...(applied ? ["apply"] : []),
    ...(!nextPreparation ? ["format"] : []), ...(state.tools?.inspector.installed && state.tools.forge.installed ? ["tools"] : [])]);
  const speakerStatus = <ActionList><ActionRow label={<><strong>{speakersConfigured ? "Speaker detection configured" : "Speaker investigation"}</strong><small>{
    speakerAction.busy ? "" : findings.status === "ready" && (draft.dirty || state.optionsDraft) ? "Save or discard your option edits to apply the findings."
      : findings.status === "missing" && taskId === "names" ? "The agent checks formats before scanning names."
      : speakersConfigured ? `${findings.rules.filter((rule) => values.engine_options[rule.key] === true).length} of ${findings.rules.length} optional rules enabled.${findings.overrides.length ? " Manual overrides retained." : ""}` : findings.message}</small></>}>
    {speakersConfigured ? <Button disabled={disabled} onClick={() => setPanel("speakers")}>View findings</Button>
      : findings.status === "ready" ? <ActionControl label={draft.dirty || state.optionsDraft ? "Save edits & apply findings" : "Apply investigated rules"} disabled={disabled}
          pending={speakerAction.busy} pendingText="Applying rules…" error={speakerAction.error}
          onClick={() => speakerAction.run(async () => { await save(); await draft.applySpeakers(); }, "Speaker rules configured.", "apply")} />
      : taskId !== "names" ? <Button disabled={disabled} onClick={() => stepTask("names")}>Open speaker discovery</Button> : null}
  </ActionRow></ActionList>;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  switch (taskId) {
    case "backup":
      content = <>{sourceBackup ? <div className="guided-backup-location"><strong>{preserved ? `${sourceBackup.files.toLocaleString()} original files preserved` : "Original backup unavailable"}</strong>
        {!preserved && <Message message={sourceBackup.issue || "A replacement saves the current game; it cannot recover the missing original."} />}
        {preserved && <p className="muted">The original game is protected. Continue with preparation.</p>}</div>
        : <p className="muted">The first backup stores this game’s original files before preparation begins.</p>}
        {sourceBackup && !preserved && <Button onClick={() => setPanel("backups")}>Recover a saved backup</Button>}</>;
      primary = preserved ? advance() : task("backup_source", sourceBackup ? "Back up current game" : "Back up original game", {}, false, "primary"); break;
    case "extract":
      content = <><p>{state.encrypted.length ? "An encrypted archive was found." : "No encrypted archive found."} {state.files.length ? "Converted JSON is available." : "Convert native Ace data to JSON before translation."}</p>
        {!state.aceAvailable && <p className="muted">Native conversion requires Windows or Wine. Existing ace_json exports can be used.</p>}
        <ActionList><ActionRow label="Extract the encrypted archive when required.">{task("ace_decrypt", "Extract archive", {}, !preserved || !state.encrypted.length || !state.aceAvailable)}</ActionRow>
          <ActionRow label="Convert native game data for the JSON translation phases.">{task("ace_extract", "Convert to JSON", {}, !preserved || !state.aceAvailable)}</ActionRow></ActionList></>;
      primary = advance(); break;
    case "format":
      content = <><ol className="guided-preparation-list">{formatActions.map((item) => { const result = operationJob(item.id); return <li key={item.id}><span className={result?.status === "complete" ? "guided-completed" : "muted"}>{result?.status === "complete" ? "✓" : nextPreparation?.id === item.id ? "→" : "·"}</span><div><strong>{item.title}</strong><small>{item.hint}</small></div></li>; })}</ol>
        <Button variant="quiet" onClick={() => setPanel("preparation")}>Preparation tools</Button></>;
      primary = nextPreparation && !baseline ? task(nextPreparation.id, nextPreparation.title, {}, !preserved, "primary") : advance(); break;
    case "baseline":
      content = baseline ? <><p className="guided-success">Original version {translation.git?.original_version || "baseline"} is saved.</p><p className="muted">Next, discover the game’s speakers and prepare its translation context.</p></> : <fieldset disabled={disabled}>
        <FieldRow id="guided-version" label="Game version">{(props) => <input {...props} value={fields.version} placeholder="1.00" onChange={(event) => editForm("version", event.target.value)} />}</FieldRow>
        <label className="toggle"><input type="checkbox" checked={fields.untranslated} onChange={(event) => editForm("untranslated", event.target.checked)} />This game is untranslated; use it as the original baseline.</label>
        {!fields.untranslated && <FieldRow id="guided-original" label="Matching original" help="Choose the prepared original matching this already-translated game.">{(props) => <div className="guided-folder-field"><input {...props} value={fields.original} onChange={(event) => editForm("original", event.target.value)} /><Button onClick={() => chooseFolder("original")}>Choose folder</Button></div>}</FieldRow>}</fieldset>;
      primary = baseline ? advance("Continue to names & context") : task("git_setup", "Review version baseline", { version: fields.version, original: fields.original, untranslated: fields.untranslated }, !preserved || !fields.version.trim() || !fields.untranslated && !fields.original, "primary"); break;
    case "names":
      content = <><ol className="guided-preparation-list">
        <li><span>{["ready", "applied"].includes(findings.status) ? "✓" : "1"}</span><div><strong>Identify speaker formats</strong><small>The agent checks name tags, first lines, variables and plugins, then saves rules supported by evidence.</small></div></li>
        <li><span>{scan.current ? "✓" : "2"}</span><div><strong>Scan speaker names</strong><small>{scan.current ? `${scan.names.length} nameplates found across ${scan.files} event files; ${Object.keys(scan.actorNames).length} actor names supplied for reference.` : "The local parser uses those rules to collect names. No API calls or name translation."}</small></div></li>
        <li><span>3</span><div><strong>Investigate glossary & context</strong><small>The agent uses the discovered names as extra evidence for terminology, characters, voice and game guidance.</small></div></li>
      </ol>
        <p className="muted">Paste the task into your coding assistant with this game’s folder open. It completes all three parts in order.</p>
        {scan.job && <JobStatus job={{ ...scan.job, label: scan.job.label || "Local speaker scan" }} />}
        {["invalid", "stale"].includes(findings.status) && <Message message={findings.message} />}
        <details><summary>Discovery results & tools</summary>{speakerStatus}
          <ActionControl label={scan.job ? "Refresh name scan" : "Run local name scan"} disabled={disabled || !["ready", "applied"].includes(findings.status)}
            {...feedback("speaker-scan", "Starting local scan…")} onClick={() => action.run(async () => { await save(); await api.translation.speakers(project.id, true); }, "", "speaker-scan")} />
          {scan.current && <div className="guided-name-list"><VirtualList items={scan.names} itemKey={pathKey} label="Discovered source speaker names" empty={<p>No names matched the confirmed formats. The agent should account for this in its investigation.</p>}>
            {(name) => <p className="guided-preview-path">{name}</p>}
          </VirtualList></div>}
          {!scan.current && scan.job?.status === "complete" && <p className="muted">The source files or speaker rules changed. Refresh the scan before using its names.</p>}
          <details><summary>Optional API name translation</summary>{fileSummary(eventFiles.length)}{connection}<p className="muted">Creates provisional translated names using the API. The local discovery task does not require this.</p>
            {task("start", "Review paid name translation", { mode: "speakers" }, !baseline || unfinished || !eventFiles.length || !state.provider.ready || !state.provider.enabled)}
          </details>
        </details>
        <div className="guided-utilities"><Button variant="quiet" onClick={() => setPanel("references")}>Reference translations</Button>
          <ActionControl label="Reload saved guidance" variant="quiet" disabled={disabled} {...feedback("reload-guidance", "Reloading…")} onClick={() => action.run(() => application.refresh(), "Saved guidance reloaded; your drafts are retained.", "reload-guidance")} /></div></>;
      primary = scan.current ? advance("Review saved glossary") : copyTask("setup", "Copy speaker & context task", "primary");
      secondary = scan.current ? copyTask("setup", "Copy task again", "quiet") : null; break;
    case "glossary": case "guidance":
      content = <><DocumentEditor documents={state.documents} drafts={context.drafts} edit={context.edit} disabled={disabled}
        names={savedNames} selectedName={taskId === "glossary" ? "glossary" : documentName} select={setDocumentName} focused showActions={false} save={context.save} discard={context.discard} /><div className="guided-utilities"><ActionControl label="Reload saved guidance" disabled={disabled} {...feedback("reload-guidance", "Reloading…")} onClick={() => action.run(() => application.refresh(), "Saved guidance reloaded; your drafts are retained.", "reload-guidance")} /></div></>;
      primary = <ActionControl label={savedNames.some((name) => context.drafts[name]) ? "Save & continue" : "Continue"} variant="primary" disabled={disabled} {...feedback("context:save", "Saving guidance…")} onClick={() => saveDocuments(savedNames)} />;
      secondary = savedNames.some((name) => context.drafts[name]) && <ActionControl label="Discard edits" disabled={disabled} {...feedback("context:discard", "Discarding…")} onClick={() => action.run(async () => { for (const name of savedNames) await context.discard(name); }, "Edits discarded.", "context:discard")} />; break;
    case "speakers":
      content = <>{speakerStatus}<Section title="Measured widths" hint="Characters">{widths}</Section>
        <label className="toggle"><input type="checkbox" disabled={disabled} checked={values.phase1_comments} onChange={(event) => edit("phase1_comments", event.target.checked)} />Include displayed comment continuations (408)</label>{copyTask("wrap", "Copy width-measurement task")}</>;
      primary = <ActionControl label="Save setup & choose scope" variant="primary" disabled={disabled} {...feedback("save-options", "Saving setup…")} onClick={() => action.run(async () => { await save(); await navigate("translate", "scope"); }, "", "save-options")} />; break;
    case "scope":
      content = <>{fileSummary()}<dl className="guided-scope-summary"><div><dt>Database & interface</dt><dd>{fileCount(databaseFiles.length)}</dd></div><div><dt>Dialogue & choices</dt><dd>{fileCount(eventFiles.length)}</dd></div></dl>
        <p className="muted">For a first pass, choose a small database and map scope. Saved results carry forward when you expand it.</p><Button variant="quiet" onClick={() => setPanel("options")}>Engine options & source refresh</Button></>;
      primary = advance("Continue to database translation"); break;
    case "database": case "dialogue": case "variables": case "advanced-run":
      content = <>{fileSummary(phaseFiles.length)}{connection}
        {taskId === "advanced-run" && <p>{enabledCodes.length} audited sources enabled. {values.engine_options.CODE122 === true && <>Variable IDs: {String(values.engine_options.CODE122_VAR_RANGES || "None")}. </>}<Button variant="quiet" onClick={() => stepTask("sources")}>Review sources</Button></p>}
        <ActionList><ActionRow label={<><strong>Cost estimate</strong><small>Calculated locally for this phase and the current settings. An estimate is not a spending cap.</small></>}>{task("start", "Estimate cost", { mode: "estimate", phase }, !baseline || !!changed.length || unfinished || !state.provider.model || !phaseFiles.length || phase === "advanced" && !advancedReady)}</ActionRow></ActionList>
        {estimate?.status === "complete" && estimate.estimate && <Estimate value={estimate.estimate} />}
        {taskId === "variables" && <p className="muted">This comparison cache is separate from the audit of variable assignments, scripts, and plugin commands.</p>}
        {unfinished && <p className="muted">Finish or resume the saved run before starting another phase or estimate.</p>}
        <div className="guided-utilities"><Button variant="quiet" onClick={() => stepTask("glossary")}>Guidance</Button><Button variant="quiet" onClick={() => setPanel("options")}>Engine options</Button></div></>;
      primary = task("start", mode === "batch" ? "Review Batch preparation" : "Review translation", { mode, phase }, !baseline || !phaseFiles.length || !!changed.length || unfinished || !state.provider.ready || !state.provider.enabled || phase === "advanced" && !advancedReady, "primary");
      secondary = outputFiles.length > 0 ? <Button disabled={action.busy} onClick={() => stepTask("apply")}>Apply & test this scope</Button> : advance(undefined, undefined, "quiet"); break;
    case "audit":
      content = <><ActionList><ActionRow label="Get ENABLE / SKIP recommendations, safe variable IDs, plugin handlers, and script patterns.">{copyTask("advanced", "Copy advanced-text audit")}</ActionRow></ActionList><p className="muted">The audit does not enable options. If it finds no additional player-visible text, skip this phase.</p></>;
      primary = advance("Review audited sources"); secondary = <Button onClick={() => stepTask("plugins")}>Skip extra text</Button>; break;
    case "sources":
      content = <><EngineOptions state={state} values={values.engine_options} keys={advanced} disabled={disabled} collapseChoices
        dependencies={{ CODE122_VAR_RANGES: "CODE122", ENABLED_PLUGINS_357: "CODE357", ENABLED_PATTERNS_355655: "CODE355655" }}
        change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} />
        {values.engine_options.CODE122 === true && <p className="muted">Use explicit audited IDs and ranges. <Button variant="quiet" onClick={() => stepTask("variables")}>Build the comparison cache</Button></p>}
        {values.engine_options.CODE122 === true && !String(values.engine_options.CODE122_VAR_RANGES || "").trim() && <Message message="Enter the variable IDs confirmed by the audit before continuing." />}
        {!enabledCodes.length && <p className="muted">No extra sources are enabled. This phase can be skipped.</p>}</>;
      primary = enabledCodes.length ? <Button variant="primary" disabled={disabled || !advancedReady} onClick={() => stepTask("advanced-run")}>Continue to audited translation</Button> : <Button variant="primary" onClick={() => stepTask("plugins")}>Skip extra text</Button>; break;
    case "plugins":
      content = <><ActionList><ActionRow label={<><strong>{state.engine === "ACE" ? "Ruby script text" : "Plugin text"}</strong><small>Inspect and translate player-visible text outside the JSON phases.</small></>}>{copyTask("plugins", "Copy " + (state.engine === "ACE" ? "Ruby" : "plugin") + " task")}</ActionRow>
        {state.engine === "MVMZ" && <ActionRow label={<><strong>Image text</strong><small>Check the editable image workspace before continuing image work with your assistant.</small></>}>{task("images_status", "Inspect image readiness", {}, !baseline)}</ActionRow>}</ActionList>
        {operationJob("images_status")?.result && <Button variant="quiet" onClick={() => inspect(operationJob("images_status")!)}>View image readiness details</Button>}
        <p className="muted">Image editing remains an assistant task. Check menu graphics and retain any excluded scope with the game’s guidance.</p></>;
      primary = advance(); break;
    case "apply":
      content = <>{fileSummary(outputFiles.length)}<dl className="guided-scope-summary"><div><dt>Saved outputs</dt><dd>{outputFiles.length ? `${fileCount(outputFiles.length)} available` : "No selected outputs available"}</dd></div>
        <div><dt>Applied to game</dt><dd>{applied ? state.readiness.runtime_edited.some((name) => outputFiles.includes(name)) ? "Applied · later game edits retained" : "Matches saved outputs" : "Ready for application review"}</dd></div></dl>
        {state.engine === "ACE" && <><p className="muted">Pack the latest JSON into native data before each playtest, including after fitting and QA edits.</p>{task("ace_pack", "Review native Ace packing", {}, !baseline || !state.aceAvailable || !state.files.length)}</>}</>;
      primary = applied ? advance("Check text fitting") : task("export_selected", "Review files to apply", {}, !baseline || !outputFiles.length || !!changed.length, "primary");
      secondary = applied && task("export_selected", "Apply outputs again", {}, !baseline || !outputFiles.length || !!changed.length); break;
    case "fitting":
      content = <><ActionList><ActionRow label={<><strong>Saved widths</strong><small>Dialogue {values.widths.width} · portrait {values.widths.faceWidth} · list {values.widths.listWidth} · notes {values.widths.noteWidth}</small></>}><Button disabled={disabled} onClick={() => setPanel("widths")}>Edit widths</Button></ActionRow></ActionList>
        <label className="toggle"><input type="checkbox" disabled={disabled} checked={fields.only_overflow} onChange={(event) => editForm("only_overflow", event.target.checked)} />Only rewrap text over its width limit</label>
        <p className="muted">Scan {fileCount(layoutFiles.length)} in the current scope. Protected control codes and original text stay intact.</p>
        {state.readiness.layout_scan && <p className="guided-success">A matching scan is available for review.</p>}</>;
      primary = state.readiness.layout_scan && !draft.dirty ? task("rewrap_apply", "Review fitting changes", layoutOptions, !baseline || !layoutFiles.length, "primary") : task("rewrap_preview", "Scan text fitting", layoutOptions, !baseline || !layoutFiles.length, "primary");
      secondary = advance("Continue to playtest", undefined, "quiet"); break;
    case "playtest":
      content = <><p>Play through the opening scene and menus. Check speaker names, choices, recurring terms, and text layout.</p><ActionList><ActionRow label="Open the working game and launch its executable."><Button onClick={() => action.run(() => window.dazedtl.openFolder("project"), "Game folder opened.", "open-game")}>Open game folder</Button></ActionRow>
        {state.engine === "MVMZ" && <ActionRow label="TL Inspector and Forge are available from Release."><Button onClick={() => stepTask("tools")}>Manage playtest tools</Button></ActionRow>}</ActionList>
        {state.engine === "ACE" && task("ace_pack", "Pack latest Ace data", {}, !baseline || !state.aceAvailable || !state.files.length)}</>;
      primary = <Button variant="primary" onClick={() => stepTask("scope")}>Return to expand translation</Button>; secondary = advance("Open text QA", undefined, "quiet"); break;
    case "qa":
      content = <><ActionList><ActionRow label="Prepare or resume the saved text-QA task for this release scope.">{task("qa_prepare", "Prepare text QA task", { focus: "release" }, !baseline)}</ActionRow>
        {qaTask && <ActionRow label="Paste the prepared task into your coding assistant."><ActionControl label="Copy prepared QA task" disabled={disabled} {...feedback("copy:qa", "Copying…")} onClick={() => action.run(() => window.dazedtl.copyText(String(qaTask.result!.handoff)), "QA task copied. Return to its saved findings when your assistant finishes.", "copy:qa")} /></ActionRow>}
        <ActionRow label="Read the saved reports after the assistant finishes.">{task("qa_status", "Refresh QA findings", { focus: "release" }, !baseline)}</ActionRow>
        <ActionRow label="Optional investigation of recurring jokes, callbacks, and terminology.">{copyTask("investigation", "Copy investigation task")}</ActionRow></ActionList>
        {qaStatus && <div className="guided-qa-status"><strong>Reported stage: {String(qaStatus.stage || "Task prepared").replaceAll("_", " ")}</strong>{qaJob && <Button variant="quiet" onClick={() => inspect(qaJob)}>View saved findings</Button>}</div>}</>;
      primary = advance("Continue to release"); break;
    case "tools": {
      const both = state.tools?.inspector.installed && state.tools.forge.installed;
      content = <><ActionList>{([['inspector', 'TL Inspector', 'Open source context from the game.'], ['forge', 'Forge', 'Edit text with the in-game overlay.']] as const).map(([key, label, description]) => <ActionRow key={key} label={<><strong>{label} <span className={state.tools?.[key].installed ? "guided-completed" : "muted"}>· {state.tools?.[key].message || "Status unavailable"}</span></strong><small>{description}</small></>}>
        <div className="guided-tool-actions">{task(key + "_install", state.tools?.[key].installed ? "Update" : "Install", {}, !baseline)}{state.tools?.[key].present && task(key + "_remove", "Remove", {}, !baseline)}</div></ActionRow>)}
        <ActionRow label={<><strong>Tool settings</strong><small>Saved: Inspector {release.tools.hotkey} · Forge {release.tools.forgeHotkey} · scale {release.tools.uiScale === "auto" ? "Auto" : Number(release.tools.uiScale) * 100 + "%"}</small></>}><Button disabled={disabled} onClick={() => setPanel("tools")}>Configure tools</Button></ActionRow>
        <ActionRow label="Create a portable player walkthrough with your coding assistant.">{copyTask("walkthrough", "Copy walkthrough task")}</ActionRow></ActionList></>;
      primary = both ? advance("Continue to packaging") : task("playtest_install", "Install both plugins", {}, !baseline, "primary"); secondary = !both && advance("Continue to packaging", undefined, "quiet"); break;
    }
    case "package":
      content = <><fieldset disabled={disabled}><div className="guided-mode" role="group" aria-label="Package type">{([['game', 'Clean game ZIP'], ['patch', 'Patch ZIP']] as const).map(([kind, label]) => <Button key={kind} aria-pressed={release.kind === kind} onClick={() => editRelease("kind", kind)}>{label}</Button>)}</div>
        <div className="guided-package-fields"><label>Archive name<input value={release.name} onChange={(event) => editRelease("name", event.target.value)} /></label><label>Save in<div className="guided-folder-field"><input aria-label="Save in" value={release.directory} onChange={(event) => editRelease("directory", event.target.value)} /><Button onClick={() => chooseFolder("release")}>Choose folder</Button></div></label></div></fieldset>
        {/[\\/]/.test(release.name) && <Message message="Use a filename without folder separators. Choose the destination in Save in." />}
        {state.engine === "ACE" && <Section title="Native Ace data"><p className="muted">Pack the latest JSON into native game data before packaging, including after fitting or QA edits.</p>{task("ace_pack", "Review native Ace packing", {}, !baseline || !state.aceAvailable || !state.files.length)}</Section>}
        <ActionList><ActionRow label={<><strong>Included</strong><small>{release.kind === "game" ? "Game runtime, translated data, plugins, assets and GameUpdate." : "The current runtime patch against the matching original version."}</small></>}><ActionControl label="View package scope" disabled={disabled || !release.directory || !release.name} {...feedback("package:inspect", "Reading package scope…")}
          onClick={() => action.run(async () => { await save(); setPreview(await api.preview(project.id, releaseAction, undefined, { output: releasePath })); }, "", "package:inspect")} /></ActionRow>
        <ActionRow label={<><strong>Omitted</strong><small>Saves, logs, caches, backups, private configuration and translator files.</small></>}><Button variant="quiet" onClick={() => setPanel("exclusions")}>View exclusions</Button></ActionRow></ActionList>
        {artifact && <div className="guided-artifact"><strong>{artifact.available ? currentArtifact ? "Saved archive available" : "Previous release available" : "Saved archive unavailable"}</strong><span className="path">{artifact.path}</span><ActionControl label="Open release folder" disabled={!artifact.available || action.busy} {...feedback("open-release", "Opening…")} onClick={() => action.run(() => window.dazedtl.openFolder("output", artifact.folder), "Release folder opened.", "open-release")} /></div>}
        <p className="muted">Packaging creates a local ZIP. {release.kind === "patch" ? "The reviewed runtime scope is checkpointed as part of the build." : "The working game stays untouched."} Publishing is separate.</p></>;
      primary = task(releaseAction, release.kind === "game" ? "Build clean game ZIP" : "Review & build patch ZIP", { output: releasePath }, !baseline || unfinished || !release.directory.trim() || !release.name.trim() || /[\\/]/.test(release.name), "primary"); break;
    default:
      content = job ? <RunPanel hideTitle job={job} active={running && ["running", "waiting"].includes(job.status)} busy={action.busy}
        pendingKey={action.busy ? action.key : ""} error={action.key.startsWith("run:") ? action.error : ""}
        stop={() => action.run(() => api.stop(project.id), "", "run:stop")} resume={() => setResume(true)} answer={(approved) => action.run(() => api.answer(project.id, job.approval!.token, approved), "", "run:answer:" + approved)}
        exportFiles={() => action.run(async () => setOutput((await api.export(project.id)).path), "Output copy saved.", "run:export")} /> : <p className="muted">No saved translation run is available for this game.</p>;
      primary = job?.status === "complete" && job.mode !== "estimate"
        ? <Button variant="primary" onClick={() => stepTask(job.mode === "speakers" ? "glossary" : runPhase(state) === "database" ? "dialogue" : runPhase(state) === "variables" ? "audit" : "apply")}>{job.mode === "speakers" ? "Review glossary" : runPhase(state) === "database" ? "Continue to dialogue" : runPhase(state) === "variables" ? "Audit extra text" : "Apply & test this scope"}</Button>
        : <Button onClick={() => stepTask(stage.tasks[0].id)}>Return to tasks</Button>;
  }
  const previous = taskIndex > 0 ? stage.tasks[taskIndex - 1] : stages[stages.indexOf(stage) - 1]?.tasks.at(-1);
  const paid = preview?.action === "start" && preview.options.mode !== "estimate";
  const savePanel = (label = "Save & close") => <ActionControl label={label} variant="primary" disabled={disabled} {...feedback("save-options", "Saving…")} onClick={() => action.run(async () => { await save(); setPanel(null); }, "Options saved.", "save-options")} />;
  return <PageLayout variant="editor" className="guided-workspace" aria-label="Translation workspace">
    <PageHeader className="guided-header" title="Translation" description={state.engine === "ACE" ? "RPG Maker VX Ace" : "RPG Maker MV / MZ"}
      actions={<div className="actions"><Button variant="quiet" onClick={() => setPanel("project-tools")}>Project tools</Button><Button variant="quiet" onClick={() => setHistory(true)}>Activity</Button><Button variant="quiet" onClick={() => action.run(() => window.dazedtl.openFolder("project"), "Game folder opened.", "open-game")}><FolderOpen size={16} />Game folder</Button></div>} />
    <div className="guided-layout">
      <WorkflowNavigation stages={stages} step={position.step} task={taskId} completed={completed} disabled={action.busy} move={move} />
      <div className="guided-task-workspace">
        {unfinished && taskId !== "run" && !["prepare", "context"].includes(position.step) && <div className="guided-attention"><span>{job?.mode === "speakers" ? "Saved name translation" : "Saved translation run"} · {job?.status}</span><Button onClick={() => move(runStage(state), "run")}>Open saved run</Button></div>}
        {activeOperation && <div className="guided-attention"><JobStatus compact job={{ ...activeOperation, label: activeOperation.label || "Current operation" }} /><Button disabled={action.busy} onClick={() => action.run(async () => { if (state.operations.some((item) => item.id === activeOperation.id)) await api.stop(project.id); else await api.translation.stop(project.id, activeOperation.id); }, "", "stop-operation")}>Stop operation</Button></div>}
        <PageBody ref={bodyRef} className="guided-task-body">
          <div className="guided-task-heading"><div className="guided-task-location"><span>{stage.title}{taskIndex >= 0 ? ` · Task ${taskIndex + 1} of ${stage.tasks.length}` : " · Saved run"}</span><Button variant="quiet" onClick={() => setPanel("tasks")}>All tasks</Button></div>
            <h2 ref={headingRef} tabIndex={-1}>{selectedTask?.title || "Saved translation run"}</h2>{selectedTask?.description && <p>{selectedTask.description}</p>}</div>
          <Message message={!preview && (!feedbackKeys.has(action.key) && !(taskId === "run" && action.key.startsWith("run:"))) ? action.error : ""} onDismiss={action.clear} />
          <Message message={state.collectionError} />
          {changed.length > 0 && ["translate", "advanced", "apply", "review"].includes(position.step) && <div className="guided-source-alert"><p>{fileCount(changed.length)} have changed sources. Review them before new work.</p>{task("refresh_sources", "Review source refresh", {}, unfinished || !baseline, "default", changed)}</div>}
          {content}
          {output && <p className="path">Output copy: {output} <Button onClick={() => action.run(() => window.dazedtl.openFolder("output", output))}>Open folder</Button></p>}
        </PageBody>
        <ActionBar feedback={<div className="guided-footer-context">{previous && <Button variant="quiet" disabled={action.busy} onClick={() => stepTask(previous.id)}>Back</Button>}<span>{draft.dirty ? "Options retained for recovery" : preserved ? "Original preserved" : "Start by preserving the original"}</span></div>}>
          {secondary}{primary}
        </ActionBar>
      </div>
    </div>
    {panel && <Modal label={panel === "files" ? "Choose files for this pass" : panel === "tasks" ? "Translation tasks" : "Translation options"} className="guided-sheet" dismissible={!action.busy} onDismiss={closePanel}>
      <header className="guided-sheet-heading"><h2>{{ tasks: "Translation tasks", files: "Choose files for this pass", backups: "Backups & recovery", versions: "Game updates", speakers: "Speaker detection", widths: "Measured line widths", options: "Engine options & source refresh", tools: "Configure playtest tools", "project-tools": "Project tools", references: "Reference translations", preparation: "Preparation tools", exclusions: "Release exclusions" }[panel]}</h2></header>
      {panel === "files" ? <FileSelection state={state} selected={values.selected} change={(names) => edit("selected", names)} disabled={disabled} /> : <div className="guided-sheet-body">
        {panel === "tasks" && <div className="guided-all-tasks">{stages.map((item) => <section key={item.id}><h3>{item.title}</h3>{item.tasks.map((entry) => <Button key={entry.id} variant="quiet" onClick={() => move(item.id, entry.id)}>{entry.title}</Button>)}</section>)}</div>}
        {panel === "project-tools" && <ActionList>
          <ActionRow label={<><strong>Move to a newer game release</strong><small>Bring a developer’s update into the game you’re translating.</small></>}><Button onClick={() => setPanel("versions")}>Game updates</Button></ActionRow>
          <ActionRow label={<><strong>Save or recover files</strong><small>Manage backups and recover an earlier copy when you need one.</small></>}><Button onClick={() => setPanel("backups")}>Backups & recovery</Button></ActionRow>
        </ActionList>}
        {panel === "backups" && backups?.(utilityActions)}{panel === "versions" && versions?.({ backups: () => setPanel("backups"), prepare: () => stepTask("baseline"), checkpoint: () => { setPanel(null); void review("checkpoint"); }, target: utilityActions })}
        {panel === "speakers" && (speakersConfigured ? <><SpeakerFindings findings={findings} values={values.engine_options} />
          <details><summary>Adjust manually</summary><p className="muted">Your overrides are retained. Recollect names after changing detection.</p>
            <EngineOptions state={state} values={values.engine_options} keys={speakers} disabled={disabled} change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} />
            {!!findings.overrides.length && <ActionControl label="Use investigation recommendations" disabled={disabled || draft.dirty || !!state.optionsDraft} pending={speakerAction.busy} pendingText="Applying rules…" error={speakerAction.error} notice={speakerAction.notice}
              onClick={() => speakerAction.run(() => draft.applySpeakers(true), "Investigation recommendations restored.", "apply")} />}
          </details></> : speakerStatus)}
        {panel === "widths" && <>{widths}{copyTask("wrap", "Copy width-measurement task")}</>}
        {panel === "options" && <><EngineOptions state={state} values={values.engine_options} keys={["IGNORETLTEXT", "PRESERVEORIGINAL", "FIXTEXTWRAP", "BRFLAG", "TLSYSTEMVARIABLES", "TLSYSTEMSWITCHES"]} disabled={disabled} change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} />
          <Section title="Start a new source pass"><p className="muted">Refresh archives selected working copies, outputs, and variable cache. Frozen runs retain their original records.</p>{task("refresh_sources", "Review selected source refresh", {}, !baseline || unfinished || !values.selected.length, "default", values.selected)}</Section></>}
        {panel === "preparation" && <ActionList>{formatActions.map((item) => <ActionRow key={item.id} label={item.hint}>{task(item.id, item.title, {}, !preserved)}</ActionRow>)}</ActionList>}
        {panel === "tools" && <><p className="muted">Settings are saved with this project. Install/update a plugin or apply settings to use them in the game.</p><fieldset disabled={disabled}><div className="guided-widths">{([["hotkey", "TL Inspector hotkey"], ["forgeHotkey", "Forge hotkey"]] as const).map(([key, label]) => <label key={key}>{label}<input value={release.tools[key]} onChange={(event) => editRelease("tools", { ...release.tools, [key]: event.target.value })} /></label>)}</div>
          <FieldRow id="guided-tool-scale" label="Overlay scale">{(props) => <select {...props} value={release.tools.uiScale} onChange={(event) => editRelease("tools", { ...release.tools, uiScale: event.target.value })}>{["auto", "1", "1.25", "1.5", "1.75", "2", "2.25", "2.5"].map((value) => <option key={value} value={value}>{value === "auto" ? "Automatic" : Number(value) * 100 + "%"}</option>)}</select>}</FieldRow>
          <FieldRow id="guided-tool-editor" label="Source editor" help="Use auto for detection, or choose the editor executable.">{(props) => <div className="guided-folder-field"><input {...props} value={release.tools.editorCmd} onChange={(event) => editRelease("tools", { ...release.tools, editorCmd: event.target.value })} /><Button onClick={() => action.run(async () => { const path = await window.dazedtl.chooseEditor(); if (path) editRelease("tools", { ...release.tools, editorCmd: path }); }, "", "choose-editor")}>Choose editor</Button></div>}</FieldRow></fieldset>
          {task("editors", "Find installed editors")}{operationJob("editors")?.result && <pre>{JSON.stringify(operationJob("editors")!.result, null, 2)}</pre>}
          <Section title="Installed plugins">{task("playtest_apply", "Apply settings to game", {}, !baseline || !state.tools?.inspector.installed && !state.tools?.forge.installed)}</Section></>}
        {panel === "references" && <ReferenceTools state={state} disabled={disabled} action={action} save={save} review={review} />}
        {panel === "exclusions" && <><p>The clean game archive omits translator work, private configuration, caches, local saves, logs, backup files and temporary files.</p><ul><li>.dazedtl and version-control metadata</li><li>Local save folders and save files</li><li>.env files and editor configuration</li><li>Translator guidance, working exports and tool scripts</li><li>Backups, caches and temporary files</li></ul><p>Player GameUpdate files remain included. Packaging never deletes these files from the working game.</p></>}
      </div>}
      <ActionBar feedback={<Message message={action.error && !feedbackKeys.has(action.key) ? action.error : ""} />}>{panel === "files" ? <><Button disabled={action.busy} onClick={closePanel}>Cancel</Button><ActionControl label={`Use ${fileCount(values.selected.length)}`} variant="primary" disabled={disabled || !values.selected.length} {...feedback("files:save", "Saving selection…")} onClick={() => action.run(async () => { await save(); setPanel(null); }, "File selection saved.", "files:save")} /></> : <><Button disabled={action.busy} onClick={() => setPanel(null)}>Close</Button><div ref={setUtilityActions} className="action-bar-slot" />{["speakers", "widths", "options", "tools"].includes(panel) && (panel !== "speakers" || draft.dirty) && <>{draft.dirty && <ActionControl label="Discard engine options" disabled={disabled} {...feedback("discard-options", "Discarding…")} onClick={() => action.run(draft.discard, "Engine options restored.", "discard-options")} />}{savePanel()}</>}</>}</ActionBar>
    </Modal>}
    {history && <Modal label="Recent activity" onDismiss={() => setHistory(false)}><h2>Recent activity</h2><ActivityHistory state={state} translation={translation} inspect={inspect} /><Button onClick={() => setHistory(false)}>Close</Button></Modal>}
    {inspected && <Modal label="Activity details" onDismiss={() => setInspected(null)}><h2>{inspected.label || "Saved activity"}</h2><JobStatus job={{ ...inspected, label: inspected.label || "Saved activity" }} />
      {inspected.files && <p>{fileCount(inspected.files.length)} frozen · {inspected.model} · {inspected.mode}</p>}
      <Message message={action.key === "inspect:" + inspected.id ? action.error : ""} />
      {inspected.result && <pre>{JSON.stringify(inspected.result, null, 2)}</pre>}
      {!!inspected.log.length && <details><summary>Diagnostic log</summary><pre>{inspected.log.join("\n")}</pre></details>}
      {inspected.status === "complete" && Object.keys(inspected.outputs || {}).length > 0 && <ActionControl label="Save this run’s output copy" disabled={action.busy || inspected.outputsAvailable === false} {...feedback("run:export", "Saving output copy…")} onClick={() => action.run(async () => setOutput((await api.export(project.id, inspected.id)).path), "Output copy saved.", "run:export")} />}
      <Button onClick={() => setInspected(null)}>Close</Button></Modal>}
    {preview && <Modal label="Review translation action" className="guided-sheet" dismissible={!action.busy} onDismiss={() => setPreview(null)}><header className="guided-sheet-heading"><h2>{preview.label}</h2></header><div className="guided-sheet-body">
      <p className="path">{preview.destination}</p>{preview.action === "start" && <p>Phase: {phaseLabels[preview.options.phase as Phase]}</p>}
      {!!preview.paths.length && <><p>{fileCount(preview.files || preview.paths.length)} in this action</p><div className="guided-preview-files"><VirtualList items={preview.paths} itemKey={pathKey} label="Files in this action" empty={null}>{(name) => <div className="guided-preview-path">{name}</div>}</VirtualList></div></>}
      {preview.package && <p>{preview.package.included.toLocaleString()} runtime files included · {preview.package.excluded.toLocaleString()} tool/private entries omitted.</p>}
      {!!preview.additions?.length && <p>{preview.additions.length} files are additions to the original baseline.</p>}
      {preview.action === "git_setup" && <p>Version {String(preview.options.version)} · {preview.options.untranslated ? "Use the selected untranslated game as the original." : "Matching original: " + String(preview.options.original)}</p>}
      {preview.action === "backup_source" && sourceBackup?.available === false && <p>This saves current files. It cannot recover the missing original.</p>}
      {preview.action === "refresh_sources" && <p>Archive these files’ working copies, outputs, and variable cache before refreshing from the original source. Frozen provider runs remain retained.</p>}
      {preview.action === "export_selected" && <p>Apply accumulated translated outputs to these runtime files.</p>}
      {preview.action === "release" && preview.confirmation && <p>Replace the existing archive at this destination after the new ZIP passes verification.</p>}
      {preview.action === "release_patch" && <p>Use this runtime scope to create a local checkpoint and patch archive. Source, ownership, scope, and destination are checked again before execution.</p>}
      {paid && <p>{state.provider.model} · {preview.options.mode === "batch" ? "Prepare this scope for a separate Batch cost approval. Speaker translation can request its own approval." : "API requests may incur charges using this run’s frozen settings."}</p>}
      {paid && preview.options.phase === "advanced" && <><p>Audited sources: {enabledCodes.join(", ")}</p>{values.engine_options.CODE122 === true && <p>Variable IDs: {String(values.engine_options.CODE122_VAR_RANGES)}</p>}{values.engine_options.CODE357 === true && <p>Plugin handlers: {(values.engine_options.ENABLED_PLUGINS_357 as string[] || []).join(", ") || "None"}</p>}{values.engine_options.CODE355655 === true && <p>Script patterns: {(values.engine_options.ENABLED_PATTERNS_355655 as string[] || []).join(", ") || "None"}</p>}</>}
      {preview.rewrap && <><p>{preview.rewrap.changes_found} fitting changes · {preview.rewrap.overflow_skipped} protected overflows skipped</p>{preview.rewrap.previews.map((row, index) => <details key={index}><summary>{row.file_name} · {row.locator}</summary><strong>Before</strong><pre>{row.before}</pre><strong>After</strong><pre>{row.after}</pre></details>)}</>}
      </div><ActionBar feedback={<Message message={action.error} />}><Button disabled={action.busy} onClick={() => setPreview(null)}>Cancel</Button><Button variant="primary" pending={action.busy} onClick={() => action.run(() => execute(preview), "", actionKey(preview.action, preview.options))}>
        {paid && preview.options.mode === "translate" ? "Approve and start Live API" : paid && preview.options.mode === "batch" ? "Prepare Batch for cost review" : preview.action === "refresh_sources" ? "Archive and refresh sources" : ["release", "release_patch"].includes(preview.action) ? "Build release ZIP" : "Run this action"}</Button></ActionBar></Modal>}
    {resume && <Modal label="Resume saved run" dismissible={!action.busy} onDismiss={() => setResume(false)}><h2>Resume the saved run?</h2><p>Continue its frozen files, context, and provider settings. Remaining requests may incur charges.</p><Message message={action.error} /><div className="actions"><Button disabled={action.busy} onClick={() => setResume(false)}>Cancel</Button><Button variant="primary" pending={action.busy} onClick={() => action.run(async () => { await api.resume(project.id); setResume(false); }, "", "run:resume")}>Resume saved run</Button></div></Modal>}
  </PageLayout>;
}

function ReferenceTools({ state, disabled, action, save, review }: {
  state: GuidedState; disabled: boolean; action: ReturnType<typeof useAction>; save: () => Promise<void>;
  review: (name: string, options?: Record<string, unknown>, files?: string[], inspectOnly?: boolean) => Promise<unknown>;
}) {
  const add = (paired: boolean) => action.run(async () => {
    const original = paired ? await window.dazedtl.chooseFolder() : null;
    if (paired && !original) return;
    const translated = await window.dazedtl.chooseFolder();
    if (!translated) return;
    await save();
    const title = translated.replace(/\\/g, "/").split("/").filter(Boolean).at(-1) || "Reference translation";
    const preview = await api.preview(state.projectId, paired ? "reference_pair" : "reference_add", undefined, { title, translated, ...(paired ? { original } : {}) });
    await api.execute(state.projectId, preview.token);
  }, "Reference preparation started.", "reference:add");
  return <><p className="muted">Register earlier translations before copying setup. Reference wording is advisory; this game’s source and guidance remain authoritative.</p>
    <ActionList><ActionRow label="Choose a translated data folder retaining DazedTL originals."><Button disabled={disabled} onClick={() => add(false)}>Add DazedTL translation</Button></ActionRow><ActionRow label="Choose the Japanese game first, then its matching English translation."><Button disabled={disabled} onClick={() => add(true)}>Add Japanese / English pair</Button></ActionRow></ActionList>
    {!!state.references?.length && <Section title="Registered references"><ActionList>{state.references.map((reference) => <ActionRow key={reference.id} label={reference.title}><Button disabled={disabled} onClick={() => review("reference_remove", { id: reference.id })}>Remove reference</Button></ActionRow>)}</ActionList><Button disabled={disabled} onClick={() => review("reference_build")}>Build exact matches</Button></Section>}
    <Message message={action.key === "reference:add" ? action.error : ""} />{action.key === "reference:add" && <p role="status">{action.busy ? "Preparing reference…" : action.notice}</p>}</>;
}
