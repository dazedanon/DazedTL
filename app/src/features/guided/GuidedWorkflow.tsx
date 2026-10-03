import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Check, FolderOpen, LoaderCircle } from "lucide-react";
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
import { retainOtherScope } from "./selection";
import RunPanel, { Estimate } from "./RunPanel";
import { ProcessPanel } from "./ProcessPanel";
import { TranslateWorkspace } from "./TranslateWorkspace";
import { useContextDraft } from "./useContextDraft";
import { useGuidedWorkflow } from "./useGuidedWorkflow";
import { initialPosition, runPhase, runStage, stagesFor, taskForStage, unfinishedRun } from "./workflow";
import { WorkflowNavigation } from "./WorkflowNavigation";
import { guidanceBlockers, guidanceNames, guidanceTitle, saveGuidanceSet } from "./guidanceReview";
import { GuidanceReview } from "./GuidanceReview";
import { SpeakerFindings } from "./SpeakerFindings";
import { EventTextSources } from "./EventTextSources";
import { EventTextPicker } from "./EventTextPicker";
import { EventTextReview, type SourceReview } from "./EventTextReview";
import { sourceErrors, type SelectorKey, type SourcePickerDraft } from "./eventTextSelection";
import { ImageManager } from "../images/ImageManager";
import { ImageTextEditor } from "../images/ImageTextEditor";
import { imagesApi } from "../../api/images";
import { GuidedImages, type ImageEntryMode } from "./GuidedImages";
import { ReleaseContent, ReleaseReview } from "./Release";
const PluginWorkspace = lazy(() => import("../plugins/PluginWorkspace").then(module => ({ default: module.PluginWorkspace })));

const speakers = ["NAMES", "FIRSTLINESPEAKERS", "INLINE401SPEAKERS", "FACENAME101", "AUTONAMEPOPUP101", "SPEAKERS408"];
const advanced = ["CODE122", "CODE122_VAR_RANGES", "CODE357", "ENABLED_PLUGINS_357", "CODE355655", "ENABLED_PATTERNS_355655", "CODE657", "CODE356", "CODE320", "CODE324", "CODE325", "CODE108"];
const advancedCodes = advanced.filter((key) => key.startsWith("CODE") && key !== "CODE122_VAR_RANGES");
const phaseLabels: Record<Phase, string> = { database: "Database & interface", dialogue: "Dialogue & choices", variables: "Update comparisons", advanced: "Other event text", speakers: "Optional name translation" };
const actionKey = (name: string, options: Record<string, unknown> = {}) => name === "start" ? `start:${options.mode}:${options.phase || "speakers"}` : name === "runtime_restore" ? `runtime_restore:${options.publication}` : name;
const jobTime = (job: { updated?: string; created?: string }) => Date.parse(job.updated || job.created || "") || 0;
const fileCount = (count: number) => `${count} ${count === 1 ? "file" : "files"}`;
const pathKey = (name: string) => name;
const publicationLabels: Record<string, string> = { rewrap_apply: "Text fitting", qa_apply: "QA corrections", runtime_restore: "Text restore", export_selected: "Text Apply" };
type Panel = "tasks" | "files" | "backups" | "versions" | "speakers" | "widths" | "options" | "translation-context" | "tools" | "project-tools" | "references" | "preparation" | "exclusions" | "release-assets" | null;
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
  const taskView = taskId === "other-event-text" ? state.eventText.view : taskId === "apply" ? fields.text.view : taskId;
  const taskIndex = stage.tasks.findIndex((item) => item.id === taskId);
  const [panel, setPanel] = useState<Panel>(null);
  const [imageView, setImageView] = useState<ImageEntryMode | null>(null);
  const [editorAssets, setEditorAssets] = useState<string[] | null>(null);
  const [utilityActions, setUtilityActions] = useState<HTMLDivElement | null>(null);
  const [pluginFooter, setPluginFooter] = useState<HTMLDivElement | null>(null);
  const [fileBaseline, setFileBaseline] = useState<string[]>([]);
  const [fileScope, setFileScope] = useState<"database" | "dialogue" | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [inspectRelease, setInspectRelease] = useState(false);
  const [resume, setResume] = useState<Job | null>(null);
  const [sourceReview, setSourceReview] = useState<SourceReview | null>(null);
  const [comparisonReview, setComparisonReview] = useState(false);
  const [comparisonsAccepted, setComparisonsAccepted] = useState(false);
  const [history, setHistory] = useState(false);
  const [inspected, setInspected] = useState<Job | null>(null);
  const [started, setStarted] = useState<Record<string, Job>>({});
  const [translateScope, setTranslateScope] = useState<"database" | "dialogue">(state.phase === "dialogue" ? "dialogue" : "database");
  const [preparingTranslation, setPreparingTranslation] = useState<{ id: string; phase: "database" | "dialogue" } | null>(null);

  const documentSelection = useDraft("guided-document:" + project.id, { initial: { saved: state.contextDocument }, report: action.report,
    persist: (document) => api.guided.position(project.id, "context", "guidance", document) });
  const documentName = documentSelection.value || state.contextDocument;
  const setDocumentName = (name: string) => documentSelection.session.edit(name);
  const [output, setOutput] = useState("");
  const [baselineRun, setBaselineRun] = useState<string | null>(null);
  const [baselineNotice, setBaselineNotice] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { bodyRef.current?.scrollTo(0, 0); headingRef.current?.focus({ preventScroll: true }); }, [taskId, taskView, position.step]);
  const running = !!application.snapshot?.application.running;
  const disabled = action.busy || speakerAction.busy || draft.committing || context.committing;
  const sourceBackup = translation.lifecycle.source_backup;
  const preserved = !!sourceBackup && sourceBackup.available !== false;
  const baseline = preserved && !!translation.git?.configured;
  const job = state.run, unfinished = unfinishedRun(state);
  const findings = state.speakerSetup;
  const speakersConfigured = findings.status === "applied";
  const scan = state.speakerScan;
  const discovery = state.contextSetup;
  const scanOptionsDirty = JSON.stringify(values.engine_options) !== JSON.stringify(state.preferences.values.engine_options) || values.phase1_comments !== state.preferences.values.phase1_comments;
  const discoveryReady = discovery.status === "ready" && !scanOptionsDirty && !Object.keys(context.drafts).length;
  const changed = state.sourceStatus.changed;
  const selectedFiles = new Set(values.selected);
  const eventFiles = state.files.filter((file) => file.group === "dialogue" && selectedFiles.has(file.name));
  const databaseFiles = state.files.filter((file) => file.group === "database" && selectedFiles.has(file.name));
  const outputFiles = state.readiness.outputs.filter((name) => selectedFiles.has(name));
  const applied = outputFiles.length > 0 && outputFiles.every((name) => state.readiness.applied.includes(name));
  const layoutFiles = state.files.filter((file) => selectedFiles.has(file.name)).map((file) => file.name);
  const enabledCodes = advancedCodes.filter((key) => values.engine_options[key] === true);
  const sourceChoicesSaved = [...advanced, "AUTONAMEPOPUP101"].every((key) => JSON.stringify(values.engine_options[key]) === JSON.stringify(state.preferences.values.engine_options[key]));
  const advancedReady = enabledCodes.length > 0 && !sourceErrors(state.eventText, values.engine_options).length && state.eventText.accepted && sourceChoicesSaved;
  const mode = values.mode;
  const paidModeReady = mode !== "batch" || state.provider.batchSupported;
  const pickerFiles = state.files.filter((file) => !fileScope || file.group === fileScope);
  const pickerSelected = values.selected.filter((name) => pickerFiles.some((file) => file.name === name));
  const phase: Phase = taskView === "advanced-run" ? "advanced" : taskView === "dialogue" ? "dialogue" : taskView === "variables" ? "variables" : "database";
  const phaseFiles = phase === "database" ? databaseFiles : eventFiles;
  const currentEstimate = (target: Phase) => !changed.length && !draft.dirty && !Object.keys(context.drafts).length && state.estimates[target]?.current ? state.estimates[target]?.job : null;
  const estimate = currentEstimate(phase);
  const activity = projectActivity(state, translation);
  const activeOperation = activity.find((item) => ["ready", "running", "waiting"].includes(item.status));
  const localOperation = !panel && activeOperation && (
    taskId === "backup" && activeOperation.action === "backup_source" ||
    taskId === "format" && ["prepare_game", "format_data", "format_plugins", "gameupdate"].includes(activeOperation.action || "")) ? activeOperation : null;
  const backupPending = taskId === "backup" && (!!localOperation || action.busy && action.key === "backup_source");
  const preparationPending = taskId === "format" && (!!localOperation || action.busy && action.key === "prepare_game");
  const stopOperation = (current: Job) => action.run(async () => {
    if (state.operations.some((item) => item.id === current.id)) await api.stop(project.id);
    else await api.translation.stop(project.id, current.id);
  }, "", "stop-operation");
  const qaTask = state.readiness.qa.current ? activity.find((item) => item.action === "qa_prepare" && item.result?.task === state.readiness.qa.task && typeof item.result?.handoff === "string") : undefined;
  const qaJob = activity.find((item) => ["qa_prepare", "qa_status"].includes(item.action || "") && item.status === "complete");
  const qa = state.readiness.qa;
  const chosenFindings = fields.text.findings_task === qa.task ? fields.text.findings : [];
  const qaStatus = qa.status;
  const release = fields.release;
  const releaseAction = release.kind === "game" ? "release" : "release_patch";
  const releasePath = release.directory.replace(/[\\/]+$/, "") + "/" + release.name;
  const artifact = state.artifacts.find((item) => item.kind === release.kind);
  const feedbackKeys = new Set<string>();

  const edit = <K extends keyof GuidedOptions>(key: K, value: GuidedOptions[K]) => draft.session.edit((current) => ({ ...current, values: { ...current.values, [key]: value } }));
  const editForm = <K extends keyof GuidedForm>(key: K, value: GuidedForm[K]) => form.session.edit((current) => ({ ...current, [key]: value }));
  const editRelease = <K extends keyof GuidedForm["release"]>(key: K, value: GuidedForm["release"][K]) => form.session.edit((current) => ({ ...current, release: { ...current.release, [key]: value } }));
  const editText = <K extends keyof GuidedForm["text"]>(key: K, value: GuidedForm["text"][K]) => form.session.edit((current) => ({ ...current, text: { ...current.text, [key]: value } }));
  const save = async () => { await flushDrafts(); if (draft.dirty || state.optionsDraft) await draft.save(); };
  const navigate = async (step: GuidedStep, task: string) => { await flushDrafts(); await api.guided.position(project.id, step, task); };
  const move = (step: GuidedStep, task: string) => action.run(async () => { await navigate(step, task); setPanel(null); }, "", "position");
  const eventStep = (view: GuidedState["eventText"]["view"]) => action.run(async () => { await flushDrafts(); await api.guided.eventTextView(project.id, view); await navigate("translate", "other-event-text"); setPanel(null); }, "", "event-text:step");
  const stepTask = (task: string) => {
    if (["audit", "sources", "advanced-run", "variables"].includes(task)) { void eventStep(task as GuidedState["eventText"]["view"]); return; }
    const owner = stages.find((item) => item.tasks.some((entry) => entry.id === task)); if (owner) void move(owner.id, task);
  };
  const openSourcePicker = (key: SelectorKey) => action.run(async () => {
    await flushDrafts();
    const selected = Array.isArray(values.engine_options[key]) ? [...values.engine_options[key] as string[]] : [];
    await api.guided.eventTextPicker(project.id, { key, selected, baseline: [...selected], query: "", filter: "all" });
  }, "", "event-text:picker");
  const saveSourcePicker = async (selection: SourcePickerDraft) => {
    const current = draft.session.getSnapshot().value!;
    if (JSON.stringify(current.values.engine_options[selection.key]) !== JSON.stringify(selection.baseline)) throw new Error("These source choices changed elsewhere. Cancel and reopen the picker.");
    draft.session.edit((value) => ({ ...value, values: { ...value.values, engine_options: { ...value.values.engine_options, [selection.key]: selection.selected } } }));
    await draft.save();
    await api.guided.eventTextPicker(project.id, null);
  };
  const reviewSources = () => action.run(async () => {
    await save(); const current = await api.guided.eventTextRequest(project.id);
    const saved = draft.session.getSnapshot().value!;
    setSourceReview({ state: current.findings, revision: saved.revision, values: saved.values.engine_options });
  }, "", "event-text:review");
  const skipEventText = () => stepTask(state.comparisons.status !== "not_needed" ? "variables" : "plugins");
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
      ...state.operations.filter((item) => item.action === name && (name !== "runtime_restore" || item.result?.restored === options.publication)),
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
    if (value.action === "git_setup") setBaselineRun(result.id);
    if (value.action === "start") {
      if (value.options.mode !== "estimate") await navigate(value.options.mode === "speakers" ? "context" : "translate", taskId === "main-text" ? "main-text" : "run");
    }
  };
  const review = (name: string, options: Record<string, unknown> = {}, files?: string[], inspectOnly = false) => action.run(async () => {
    await save();
    const { phase, ...requestOptions } = options;
    if (name === "start" && phase) await api.phase(project.id, phase as Phase);
    setInspectRelease(inspectOnly && ["release", "release_patch"].includes(name));
    const result = await api.preview(project.id, name, files, requestOptions);
    const prepareBatch = name === "start" && options.mode === "batch";
    if ((!result.confirmation || prepareBatch) && !inspectOnly) await execute(result); else setPreview(result);
  }, "", actionKey(name, options));
  const task = (name: string, label: string, options: Record<string, unknown> = {}, blocked = false, variant: "default" | "primary" = "default", files?: string[]) => {
    const recorded = name === "start" ? options.mode === "estimate" ? state.estimates[options.phase as Phase]?.job || undefined : undefined : operationJob(name, options);
    const current = name === "backup_source" && recorded?.status === "complete" ? undefined : recorded;
    const active = current && ["ready", "running", "waiting"].includes(current.status);
    const publicationReview = ["export_selected", "rewrap_apply", "qa_apply"].includes(name);
    const qaOperation = ["qa_prepare", "qa_status"].includes(name);
    const display = current?.status === "complete" && (publicationReview || qaOperation && (!qa.current || current.result?.task !== qa.task)) ? undefined : current;
    const localFeedback = !panel && (taskId === "backup" && name === "backup_source" || taskId === "format" && name === "prepare_game");
    if (localFeedback) return <Button variant={variant} pending={!!active || action.busy && action.key === actionKey(name, options)} disabled={disabled || blocked} onClick={() => review(name, options, files)}>{label}</Button>;
    if (localOperation?.action === name) return <Button variant={variant} pending disabled>{label}</Button>;
    return <ActionControl label={label} disabled={disabled || blocked} variant={variant}
      {...feedback(actionKey(name, options), active ? current.message || "Working…" : name === "start" && options.mode === "estimate" ? "Estimating selected files…" : "Preparing action…")}
      pending={action.busy && action.key === actionKey(name, options) || !!active}
      job={display && !active && !(options.mode === "estimate" && display.status === "complete") ? display : undefined}
      onClick={() => review(name, options, files)} />;
  };
  const copyTask = (name: string, label: string, variant: "default" | "primary" | "quiet" = "default") => <ActionControl label={label} variant={variant} disabled={disabled} {...feedback("copy:" + name, "Copying…")}
    onClick={() => action.run(async () => { await save(); await window.dazedtl.copyText((await api.guided.skill(project.id, name)).text); }, name === "setup" ? "" : "Task copied. Return to its saved results when your assistant finishes.", "copy:" + name)} />;
  const inspect = (item: Job) => {
    setHistory(false); setInspected(item);
    void action.run(async () => { const saved = await api.guided.inspect(project.id, item.id); setInspected((current) => current?.id === item.id ? saved : current); }, "", "inspect:" + item.id);
  };
  const chooseFiles = (scope: "database" | "dialogue" | null = null) => { setFileScope(scope); setFileBaseline([...values.selected]); setPanel("files"); };
  const beginTranslation = () => action.run(async () => {
    await save();
    await api.phase(project.id, translateScope);
    const local = await api.preview(project.id, "start", undefined, { mode: "estimate" });
    const result = await api.execute(project.id, local.token);
    setPreparingTranslation({ id: result.id, phase: translateScope });
  }, "", "translate:prepare");
  useEffect(() => {
    if (!preparingTranslation) return;
    if (taskId !== "main-text") { setPreparingTranslation(null); return; }
    if (action.busy) return;
    const quote = state.estimates[preparingTranslation.phase]?.job;
    if (quote?.id !== preparingTranslation.id || ["running", "waiting", "ready"].includes(quote.status)) return;
    setPreparingTranslation(null);
    if (quote.status !== "complete") { action.report(quote.message || "Local preparation failed.", "translate:prepare"); return; }
    void review("start", { mode, phase: preparingTranslation.phase });
  }, [preparingTranslation, state.estimates, taskId, action.busy]);
  const closePanel = () => panel === "files" ? action.run(async () => { edit("selected", fileBaseline); await flushDrafts(); setPanel(null); }, "", "files:cancel") : setPanel(null);
  const chooseFolder = (key: "original" | "release") => action.run(async () => {
    const folder = await window.dazedtl.chooseFolder();
    if (folder) key === "original" ? editForm("original", folder) : editRelease("directory", folder);
  }, "", "folder:" + key);
  const savedNames = guidanceNames(state.documents, context.drafts);
  const saveDocuments = (names: string[], target = next()) => action.run(async () => {
    const blockers = guidanceBlockers(names, state.documents, context.drafts, discovery);
    if (blockers.length) throw new Error(`Resolve ${blockers.map(guidanceTitle).join(", ")} before continuing.`);
    await saveGuidanceSet(names, context.save, (name, saved) => api.guided.reviewContext(project.id, name,
      saved[name]?.revision || state.documents[name].revision,
      discovery.documents[name]?.intentionalEmpty && !(context.drafts[name] || state.documents[name]).text.trim() ? "empty" : "review"));
    if (target) { const owner = stages.find((item) => item.tasks.some((entry) => entry.id === target.id))!; await navigate(owner.id, target.id); }
  }, "Guidance saved.", "context:save");
  const keepEmpty = (name: string) => action.run(async () => {
    const text = (context.drafts[name] || state.documents[name]).text;
    if (text.trim()) throw new Error("Clear the document before choosing to keep it empty.");
    if (!context.drafts[name]) context.edit(name, "", state.documents[name].revision);
    const saved = await context.save(name);
    await api.guided.reviewContext(project.id, name, saved[name].revision, "empty");
  }, "Empty guidance kept intentionally.", "context:empty");
  const contextBlockers = guidanceBlockers(savedNames, state.documents, context.drafts, discovery);
  const layoutOptions = { files: layoutFiles, widths: values.widths, categories: fields.text.categories, codes: fields.text.codes, max_rows: fields.text.max_rows, protect_rows: fields.text.protect_rows, over_limit: fields.only_overflow };
  const fitting = activity.find((item) => item.id === state.readiness.layout_scan)?.result as Preview["rewrap"] | undefined;
  const fittingSettingsSaved = fields.only_overflow === state.form.only_overflow && ["categories", "codes", "max_rows", "protect_rows"].every(key => JSON.stringify(fields.text[key as keyof GuidedForm["text"]]) === JSON.stringify(state.form.text[key as keyof GuidedForm["text"]]));
  const textView = (view: GuidedForm["text"]["view"]) => action.run(async () => { editText("view", view); await flushDrafts(); }, "", "text:view");
  const releaseButton = <Button variant="quiet" disabled={action.busy || form.committing} onClick={() => stepTask("package")}>Continue to Release</Button>;
  const widths = <fieldset disabled={disabled} className="guided-widths">{([["width", "Dialogue"], ["faceWidth", "With portrait"], ["listWidth", "List / help"], ["noteWidth", "Notes"]] as const).map(([key, label]) =>
    <label key={key}>{label}<input aria-label={label + " width in characters"} type="number" min={20} max={key === "faceWidth" ? values.widths.width : 300} value={values.widths[key]}
      onChange={(event) => edit("widths", { ...values.widths, [key]: Number(event.target.value) })} /></label>)}</fieldset>;
  const fileSummary = (count = values.selected.length, scope: "database" | "dialogue" | null = null) => <ActionList><ActionRow label={<><strong>{fileCount(count)} selected</strong><small>Selections remain checked when you filter, switch phases, or return later.</small></>}><Button disabled={disabled} onClick={() => chooseFiles(scope)}>Choose files</Button></ActionRow></ActionList>;
  const connection = <div className="guided-connection"><div><span>{state.provider.connection} · {state.provider.model || "No model selected"}</span><Button variant="quiet" onClick={settings}>Connection & model</Button></div><div className="guided-mode" role="group" aria-label="Translation mode">
    <Button aria-pressed={mode === "translate"} disabled={disabled} onClick={() => edit("mode", "translate")}>Live API</Button>
    {state.provider.batchSupported && <Button aria-pressed={mode === "batch"} disabled={disabled} onClick={() => edit("mode", "batch")}>Batch API</Button>}
    </div>{!state.provider.ready && <p className="muted">Configure a connection before paid translation.</p>}{!state.provider.enabled && <p className="muted">Provider execution is disabled for this launch. Local estimates are available.</p>}</div>;
  const formatActions = [{ id: "format_data", title: "Format game data", hint: "Prepare the JSON used by the translation phases." },
    ...(state.hasPlugins ? [{ id: "format_plugins", title: "Format plugins.js", hint: "Prepare the game’s plugin configuration." }] : []),
    { id: "gameupdate", title: "Create GameUpdate files", hint: "Add player patch support." }];
  const preparation = state.preparation;
  const preparationComplete = preparation.complete;
  const aceNeedsExport = state.engine === "ACE" && !state.files.length;
  useEffect(() => {
    if (!baselineRun || action.busy || taskId !== "baseline") return;
    const saved = translation.jobs.find((item) => item.id === baselineRun);
    if (saved?.status === "complete" && baseline) {
      setBaselineRun(null);
      setBaselineNotice(`Version ${translation.git?.original_version || "baseline"} saved. Prepare complete.`);
      void move("context", "names");
    } else if (saved && ["failed", "stopped", "interrupted", "canceled"].includes(saved.status)) setBaselineRun(null);
  }, [baselineRun, translation.jobs, baseline, taskId, action.busy]);
  const applyRun = (current: Job) => <Button variant="primary" disabled={disabled || !current.outputsAvailable || !baseline} onClick={() => review("export_selected", {}, Object.keys(current.outputs || {}))}>Apply translated output</Button>;
  const nextRun = (current: Job) => <Button disabled={action.busy} onClick={() => { if (current.logicalPhase === "database") { void move("translate", "main-text").then(() => requestAnimationFrame(() => bodyRef.current?.querySelector('section[aria-label="Dialogue & choices"]')?.scrollIntoView({ block: "start" }))); return; } stepTask( current.logicalPhase === "dialogue" ? "audit" : current.logicalPhase === "advanced" && state.comparisons.status !== "not_needed" ? "variables" : "plugins"); }}>{current.logicalPhase === "database" ? "Continue to dialogue" : current.logicalPhase === "dialogue" ? "Continue to other event text" : current.logicalPhase === "advanced" && state.comparisons.status !== "not_needed" ? "Update comparisons" : "Continue to plugin text"}</Button>;
  const completed = new Set<string>([...(preserved ? ["backup"] : []), ...(baseline ? ["baseline"] : []), ...(applied ? ["apply"] : []), ...((!databaseFiles.length || state.phaseRuns.database?.scopeComplete) && (!eventFiles.length || state.phaseRuns.dialogue?.scopeComplete) && values.selected.length ? ["main-text"] : []), ...(state.phaseRuns.advanced?.scopeComplete && (state.comparisons.status === "not_needed" || state.comparisons.status === "ready" && state.phaseRuns.variables?.scopeComplete) ? ["other-event-text"] : []),
    ...(discoveryReady ? ["names"] : []), ...(savedNames.every((name) => discovery.documents[name]?.reviewed && !context.drafts[name]) ? ["guidance"] : []), ...(discovery.layoutStatus === "saved" && !draft.dirty ? ["speakers"] : []), ...(preparationComplete || baseline ? ["format"] : []), ...(state.tools?.inspector.installed && state.tools.forge.installed ? ["tools"] : [])]);
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
  switch (taskView) {
    case "backup":
      content = <>{sourceBackup ? <div className="guided-backup-location"><strong className={preserved ? "guided-success" : ""}>{preserved ? `${sourceBackup.files.toLocaleString()} original files preserved` : "Original backup unavailable"}</strong>
        {!preserved && <Message message={sourceBackup.issue || "A replacement saves the current game; it cannot recover the missing original."} />}
        {preserved && <Button variant="link" onClick={() => setPanel("backups")}>Backups & recovery</Button>}</div>
        : <p className="muted">A recovery copy will be saved inside this game’s folder.</p>}
        {!preserved && operationJob("backup_source") && <JobStatus compact job={{ ...operationJob("backup_source")!, label: "Back up original game" }} />}
        {sourceBackup && !preserved && <Button onClick={() => setPanel("backups")}>Recover a saved backup</Button>}</>;
      primary = preserved ? advance() : task("backup_source", backupPending ? "Backing up…" : sourceBackup ? "Back up current game" : "Back up original game", {}, false, "primary");
      secondary = localOperation && <Button disabled={action.busy} onClick={() => stopOperation(localOperation)}>Stop backup</Button>; break;
    case "extract":
      content = <><p>{state.encrypted.length ? "An encrypted archive was found." : "No encrypted archive found."} {state.files.length ? "Converted JSON is available." : "Convert native Ace data to JSON before translation."}</p>
        {!state.aceAvailable && <p className="muted">Native conversion requires a supported Windows environment. Existing ace_json exports can be used.</p>}
        <ActionList><ActionRow label="Extract the encrypted archive when required.">{task("ace_decrypt", "Extract archive", {}, !preserved || !state.encrypted.length || !state.aceAvailable)}</ActionRow>
          <ActionRow label="Convert native game data for the JSON translation phases.">{task("ace_extract", "Convert to JSON", {}, !preserved || !state.aceAvailable)}</ActionRow></ActionList></>;
      primary = aceNeedsExport ? <Button variant="primary" disabled>Continue to prepare game files</Button> : advance(); break;
    case "format":
      content = <>{aceNeedsExport && !baseline && <div className="guided-prerequisite"><strong>Convert Ace data first</strong><Button variant="link" onClick={() => stepTask("extract")}>Return to Ace extraction</Button></div>}
        {baseline && !preparationComplete ? <p className="guided-success">The version baseline is already saved. Preparation does not need to be repeated.</p> : <ol className="guided-preparation-list">{preparation.stages.map((item) => <li key={item.action}>
        <span className={item.status === "complete" ? "guided-completed" : "muted"}>{item.status === "complete" ? <Check size={16} /> : item.status === "running" ? <LoaderCircle size={16} className="job-status-spinner" /> : "·"}</span>
        <div><strong>{item.label}</strong>{item.message && <small>{item.message}</small>}</div>
        <span className="guided-preparation-state">{item.status === "complete" ? "Done" : item.status === "pending" ? "Waiting" : item.status.replaceAll("_", " ")}</span>
      </li>)}</ol>}
        {preparation.configuration && <p className="muted">{preparation.configuration}</p>}
        {localOperation && <JobStatus compact job={{ ...localOperation, label: localOperation.label || "Current operation" }} />}
        {!localOperation && !preparationComplete && operationJob("prepare_game") && operationJob("prepare_game")!.status !== "complete" && !preparation.stages.some((item) => item.message) && <JobStatus compact job={{ ...operationJob("prepare_game")!, label: "Prepare game files" }} />}
        <Button variant="quiet" onClick={() => setPanel("preparation")}>Preparation tools</Button></>;
      primary = (preparationComplete || baseline) && !preparationPending ? advance() : task("prepare_game", preparationPending ? "Preparing game files…" : "Prepare game files", {}, !preserved || aceNeedsExport, "primary");
      secondary = localOperation && <Button disabled={action.busy} onClick={() => stopOperation(localOperation)}>Stop preparation</Button>; break;
    case "baseline":
      content = baseline ? <><p className="guided-success">Original version {translation.git?.original_version || "baseline"} is saved.</p><p className="muted">Next, discover the game’s speakers and prepare its translation context.</p></> : <>
        {!preparationComplete && <div className="guided-prerequisite"><strong>Complete game preparation first</strong><Button variant="link" onClick={() => stepTask("format")}>Return to preparation</Button></div>}
        <fieldset disabled={disabled}>
          <FieldRow id="guided-version" label="Game version">{(props) => <input {...props} value={fields.version} placeholder="e.g. 1.2.3" onChange={(event) => editForm("version", event.target.value)} />}</FieldRow>
          <fieldset className="guided-baseline-choice"><legend>Translation state</legend>
            <label><input type="radio" name="baseline-source" checked={fields.untranslated === true} onChange={() => editForm("untranslated", true)} />This game is untranslated</label>
            <label><input type="radio" name="baseline-source" checked={fields.untranslated === false} onChange={() => editForm("untranslated", false)} />This game already contains translations</label>
          </fieldset>
          {fields.untranslated === false && <FieldRow id="guided-original" label="Matching original folder" help="Choose the prepared original matching this already-translated game.">{(props) => <div className="guided-folder-field"><input {...props} value={fields.original} placeholder="Select matching original game folder" onChange={(event) => editForm("original", event.target.value)} /><Button onClick={() => chooseFolder("original")}>Browse…</Button></div>}</FieldRow>}
        </fieldset></>;
      primary = baseline ? advance("Continue to names & context") : task("git_setup", "Review version baseline", { version: fields.version, original: fields.untranslated ? "" : fields.original, untranslated: fields.untranslated }, !preserved || !preparationComplete || fields.untranslated === null || !fields.version.trim() || !fields.untranslated && !fields.original.trim(), "primary"); break;
    case "names":
      content = <><ActionList><ActionRow label={<><strong>Reference translations</strong><small>Optional · {state.references.length ? `${state.references.length} registered` : "None added"}</small></>}><Button disabled={disabled} onClick={() => setPanel("references")}>Manage references</Button></ActionRow></ActionList>
        <details className="guided-discovery-settings"><summary>Discovery settings & results</summary>
          <p className="muted">Discovery examines all event files. Choose displayed comment text before copying the task.</p>
          <label className="toggle"><input type="checkbox" disabled={disabled} checked={values.phase1_comments} onChange={(event) => edit("phase1_comments", event.target.checked)} />Include displayed comment text (408)</label>
          {speakerStatus}<Button variant="quiet" disabled={disabled} onClick={() => setPanel("speakers")}>Adjust speaker formats manually</Button>
          <ActionControl label={scan.job ? "Refresh name scan" : "Run local name scan"} disabled={disabled || !["ready", "applied"].includes(findings.status)}
            {...feedback("speaker-scan", "Starting local scan…")} onClick={() => action.run(async () => { await save(); await api.translation.speakers(project.id, true); }, "", "speaker-scan")} />
          {scan.current && <div className="guided-name-list"><VirtualList items={scan.names} itemKey={pathKey} label="Discovered source speaker names" empty={<p>No names matched the confirmed formats. Account for this in the investigation.</p>}>{(name) => <p className="guided-preview-path">{name}</p>}</VirtualList></div>}
          {(!scan.current || scanOptionsDirty) && scan.job?.status === "complete" && <p className="guided-status-warning">Name scan needs refreshing. Saved guidance is retained for review.</p>}
          <details><summary>Optional API name translation</summary>{fileSummary(eventFiles.length)}{connection}<p className="muted">Creates provisional translated names using the API. Discovery does not require this.</p>{task("start", "Review paid name translation", { mode: "speakers" }, !baseline || !eventFiles.length || !state.provider.ready || !state.provider.enabled)}</details>
        </details>
        <ol className="guided-preparation-list">
          <li><span>{["ready", "applied"].includes(findings.status) ? <Check size={16} /> : "1"}</span><div><strong>Identify speaker formats</strong><small>{["ready", "applied"].includes(findings.status) ? "Speaker-format guidance saved." : "Check names, variables, faces and plugins before scanning."}</small></div><span className="guided-preparation-state">{["ready", "applied"].includes(findings.status) ? "Saved" : findings.status === "invalid" || findings.status === "stale" ? "Needs attention" : "Waiting"}</span></li>
          <li><span>{scan.current && !scanOptionsDirty ? <Check size={16} /> : "2"}</span><div><strong>Scan speaker names</strong><small>{scan.current && !scanOptionsDirty ? `${scan.names.length} nameplates found across ${scan.files} event files.` : "The local parser collects names using the confirmed formats."}</small></div><span className="guided-preparation-state">{scan.current && !scanOptionsDirty ? "Saved" : scan.job?.status === "running" ? "Scanning" : scan.job ? "Needs attention" : "Waiting"}</span></li>
          <li><span>{discoveryReady ? <Check size={16} /> : "3"}</span><div><strong>Save glossary & context</strong><small>{discovery.message}</small></div><span className="guided-preparation-state">{discoveryReady ? "Saved" : ["stale", "invalid"].includes(discovery.status) ? "Needs attention" : "Waiting"}</span></li>
        </ol>
        {scan.job && scan.job.status !== "complete" && <JobStatus job={{ ...scan.job, label: "Local speaker scan" }} />}
        {["invalid", "stale"].includes(findings.status) && <Message message={findings.message} />}
        {discovery.requestId && !discoveryReady && <p className="muted">Task copied. Waiting for saved results.</p>}
        <div className="guided-utilities">{discovery.requestId && copyTask("setup", "Copy task again", "quiet")}
          {Object.values(discovery.documents).some((document) => document.exists) && <Button variant="quiet" disabled={disabled} onClick={() => stepTask("guidance")}>Use existing guidance</Button>}</div>
        {Object.values(discovery.documents).some((document) => document.exists) && <p className="muted">Skip new discovery and review the saved files.</p>}</>;
      primary = discoveryReady ? advance("Review translation guidance") : discovery.requestId ? <ActionControl label="Check saved results" variant="primary" disabled={disabled} {...feedback("context:check", "Checking saved results…")} onClick={() => action.run(async () => { await save(); const current = await api.guided.context(project.id); if (current.status !== "ready") throw new Error(current.message); }, "All saved investigation results verified.", "context:check")} /> : copyTask("setup", "Copy speaker & context task", "primary"); break;
    case "guidance":
      content = <><GuidanceReview documents={state.documents} context={context} setup={discovery} names={savedNames} selectedName={documentName} select={setDocumentName} disabled={disabled}
        returnToDiscovery={() => stepTask("names")} keepEmpty={keepEmpty} busy={action.busy ? action.key : ""} run={(operation) => action.run(operation, "", "context:resolve")} />
        <div className="guided-utilities"><ActionControl label="Reload saved guidance" variant="quiet" disabled={disabled} {...feedback("reload-guidance", "Reloading…")} onClick={() => action.run(() => application.refresh(), "Saved guidance reloaded; your drafts are retained.", "reload-guidance")} /></div></>;
      primary = <ActionControl label={savedNames.some((name) => context.drafts[name]) ? "Save all & continue" : "Continue to layout settings"} variant="primary" disabled={disabled || !!contextBlockers.length} {...feedback("context:save", "Saving guidance…")} onClick={() => saveDocuments(savedNames)} />;
      secondary = context.drafts[documentName] && <ActionControl label="Discard this draft" disabled={disabled} {...feedback("context:discard", "Discarding…")} onClick={() => action.run(() => context.discard(documentName), "This draft discarded.", "context:discard")} />; break;
    case "speakers":
      content = <div className="guided-layout-review"><strong className={discovery.layout ? "guided-success" : ""}>{draft.dirty ? "Unsaved edits" : discovery.layout ? "Recommendations available" : discovery.layoutStatus === "saved" ? "Saved project values" : "Defaults - not measured for this game"}</strong>
        <Section title="Character limits" hint="Characters">{widths}</Section>
        {discovery.layout && <><Button disabled={disabled} onClick={() => edit("widths", { ...discovery.layout!.widths })}>Use recommendations</Button><details><summary>Evidence & exceptions</summary><p>{discovery.layout.reason}</p><ul>{discovery.layout.evidence.map((ref, index) => <li key={index}><span className="path">{ref.file}</span>: {ref.location}</li>)}</ul></details></>}
        {copyTask("wrap", discovery.layout ? "Copy remeasurement task" : "Copy width-measurement task", "quiet")}
        <p className="muted">Optional · get fresh evidence before changing these values.</p></div>;
      primary = <ActionControl label={discovery.layoutStatus === "defaults" && !draft.dirty && !discovery.layout ? "Use current defaults & translate" : "Save layout & translate"} variant="primary" disabled={disabled} {...feedback("save-options", "Saving layout…")} onClick={() => action.run(async () => { await save(); const current = await api.guided.context(project.id); await api.guided.reviewContext(project.id, "layout", current.layoutRevision, "layout"); await navigate("translate", "main-text"); }, "", "save-options")} />; break;
    case "main-text":
      { const scopeRuns = state.runs.filter(run => run.logicalPhase === translateScope && run.mode !== "estimate");
        const current = scopeRuns.find(run => ["running", "waiting"].includes(run.status)) ||
          scopeRuns.find(run => run.mode === "batch" && run.process?.batches?.some(batch => ["validating", "in_progress", "finalizing"].includes(batch.status))) || scopeRuns[0];
        const quote = currentEstimate(translateScope);
        content = <>{current?.approval && <section className="translate-cost-review" aria-label="Final submission cost"><h3>{current.approval.kind === "batch" ? "Review submission cost" : "Review speaker translation cost"}</h3><p>{current.model} · {fileCount(current.files?.length || 0)} · saved run settings</p><p className="path">{current.files?.join(", ")}</p><Estimate value={current.approval.detail} /><p>Submit incurs API charges for this prepared scope.</p></section>}
          <TranslateWorkspace state={state} scope={translateScope} mode={mode} run={current} estimate={quote}
          pending={!!preparingTranslation || action.busy && action.key === "translate:prepare"} disabled={disabled}
          scopeChange={scope => { setPreparingTranslation(null); setTranslateScope(scope); }} modeChange={value => edit("mode", value)}
          settings={settings} files={() => chooseFiles(translateScope)} guidance={() => setPanel("translation-context")} requests={inspect} />
          {!baseline && <p className="guided-status-warning">Preserve the original and save its version baseline before translating.</p>}
          {!paidModeReady && <Message message="This connection does not support Batch. Choose Live API or a supported connection." />}</>;
        primary = current?.approval ? <Button variant="primary" disabled={disabled} pending={action.busy && action.key === "run:answer:true"}
          onClick={() => action.run(() => api.answer(project.id, current.approval!.token, true), "", "run:answer:true")}>Submit {current.approval.kind === "batch" ? "Batch" : "speakers"}</Button>
          : <Button variant="primary" pending={!!preparingTranslation || action.busy && action.key === "translate:prepare"}
            disabled={disabled || !!preparingTranslation || !baseline || !!changed.length || !(translateScope === "database" ? databaseFiles : eventFiles).length || !state.provider.model || !paidModeReady}
            onClick={beginTranslation}>{preparingTranslation ? "Preparing estimate…" : "Translate"}</Button>;
        secondary = preparingTranslation ? <Button onClick={() => setPreparingTranslation(null)}>Cancel preparation</Button>
          : current?.approval ? <Button disabled={disabled} onClick={() => action.run(() => api.answer(project.id, current.approval!.token, false), "", "run:answer:false")}>Decline</Button>
          : current && ["running", "waiting"].includes(current.status) ? <Button disabled={disabled} onClick={() => action.run(() => api.stop(project.id, current.id), "", "run:stop")}>{current.mode === "batch" ? "Pause local monitoring" : "Stop after current work"}</Button>
          : current?.mode === "batch" && ["stopped", "interrupted"].includes(current.status) && current.phase?.startsWith("poll") && current.process?.submitted ? <Button disabled={disabled} onClick={() => setResume(current)}>Resume local monitoring</Button>
          : <Button variant="quiet" onClick={() => stepTask("audit")}>Other event text</Button>;
        break; }
    case "variables": case "advanced-run":
      content = <>{fileSummary(phaseFiles.length, "dialogue")}{connection}
        {taskView === "advanced-run" && <p>{enabledCodes.length} sources selected. {state.eventText.accepted ? state.eventText.manual.length ? "Manual coverage confirmed." : "Source choices reviewed." : "Source review needed."} {values.engine_options.CODE122 === true && <>Variable IDs: {String(values.engine_options.CODE122_VAR_RANGES || "None")}. </>}<Button variant="quiet" onClick={() => stepTask("sources")}>Review sources</Button></p>}
        <ActionList><ActionRow label={<><strong>{!estimate && state.estimates[phase]?.job ? "Estimate needs refreshing" : "Cost estimate"}</strong><small>Calculated locally for this phase and the current settings. An estimate is not a spending cap.</small></>}>{task("start", "Estimate cost", { mode: "estimate", phase }, !baseline || !!changed.length || !state.provider.model || !phaseFiles.length || phase === "advanced" && !advancedReady || phase === "variables" && state.comparisons.status !== "ready")}</ActionRow></ActionList>
        {estimate?.status === "complete" && estimate.estimate && <Estimate value={estimate.estimate} />}
        {taskView === "variables" && <><ActionList><ActionRow label={<><strong>{state.comparisons.status === "not_needed" ? "Comparison update not needed" : state.comparisons.status === "recovery_needed" ? "Saved mappings need recovery" : state.comparisons.status === "ready" ? "Comparison coverage reviewed" : "Comparison review needed"}</strong><small>{state.comparisons.message}</small></>}>
          {state.comparisons.status === "recovery_needed" ? <Button disabled={disabled} onClick={() => setPanel("backups")}>Backups & recovery</Button> : state.comparisons.matches > 0 ? <Button disabled={disabled} onClick={() => { setComparisonsAccepted(false); setComparisonReview(true); }}>Review matching comparisons</Button> : null}
        </ActionRow></ActionList><Button variant="quiet" disabled={disabled} onClick={() => stepTask("plugins")}>Continue without updating comparisons</Button></>}
        {taskView === "variables" && state.comparisons.matches > 0 && <p className="muted">{state.comparisons.matches} matching comparisons in {fileCount(state.comparisons.files.length)}. {state.comparisons.unmatched > 0 && <>{state.comparisons.unmatched} unmatched literals will remain unchanged.</>}</p>}
        <div className="guided-utilities"><Button variant="quiet" onClick={() => stepTask("guidance")}>Guidance</Button><Button variant="quiet" onClick={() => setPanel("options")}>Engine options</Button></div></>;
      primary = task("start", mode === "batch" ? "Review Batch preparation" : "Review translation", { mode, phase }, !baseline || !phaseFiles.length || !!changed.length || !state.provider.ready || !state.provider.enabled || !paidModeReady || !estimate || phase === "advanced" && !advancedReady || phase === "variables" && state.comparisons.status !== "ready", "primary");
      if (state.phaseRuns[phase]?.scopeComplete) content = <>{content}<div className="guided-utilities">{primary}</div></>;
      secondary = state.phaseRuns[phase]?.scopeComplete ? <Button disabled={disabled} onClick={() => phase === "advanced" ? skipEventText() : stepTask("plugins")}>{phase === "advanced" && state.comparisons.status !== "not_needed" ? "Review comparisons" : "Continue to plugin text"}</Button> : <Button disabled={disabled} onClick={() => stepTask(phase === "advanced" ? "sources" : "advanced-run")}>Back to {phase === "advanced" ? "source choices" : "translation"}</Button>;
      if (state.phaseRuns[phase]?.scopeComplete) primary = applyRun(state.phaseRuns[phase]!);
      break;
    case "audit":
      content = <>{fileSummary(eventFiles.length, "dialogue")}<ActionList><ActionRow label={<><strong>Investigate source coverage</strong><small>Check every affected use and internal reference before selecting variable IDs, registered handlers or patterns. Found commands and argument keys return as evidence.</small></>}>{copyTask("advanced", "Copy investigation task")}</ActionRow></ActionList>
        <p className="muted">{state.eventText.message}</p><p className="muted">The copied task saves findings. It does not enable controls, edit engine code, start translation, or call providers.</p>
        <Button disabled={disabled} onClick={() => action.run(() => application.refresh(), "Findings refreshed.", "event-text:refresh")}>Refresh findings</Button></>;
      primary = <Button variant="primary" disabled={disabled} onClick={() => stepTask("sources")}>{state.eventText.status === "ready" ? "Review findings & source choices" : "Review sources manually"}</Button>;
      secondary = <Button disabled={disabled} onClick={skipEventText}>Continue without other event text</Button>; break;
    case "sources":
      content = <>{fileSummary(eventFiles.length, "dialogue")}<EventTextSources state={state.eventText} values={values.engine_options} disabled={disabled}
        change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} openPicker={openSourcePicker}
        recommendations={() => action.run(async () => { edit("engine_options", { ...values.engine_options, ...state.eventText.recommended }); await flushDrafts(); }, "Recommendations staged. Review source choices before continuing.", "event-text:recommendations")} />
        <Button variant="quiet" disabled={disabled} onClick={() => stepTask("audit")}>Back to investigation</Button></>;
      primary = enabledCodes.length ? <Button variant="primary" disabled={disabled || !!sourceErrors(state.eventText, values.engine_options).length || !eventFiles.length} onClick={reviewSources}>Review source choices</Button> : <Button variant="primary" disabled={disabled} onClick={skipEventText}>Continue without other event text</Button>;
      secondary = state.eventText.accepted && !draft.dirty && enabledCodes.length ? <Button disabled={disabled} onClick={() => stepTask("advanced-run")}>Continue to translation</Button> : null; break;
    case "plugins":
      content = <Suspense fallback={<p role="status">Loading plugin workspace…</p>}><PluginWorkspace key={project.id} projectId={project.id} observed={application.snapshot?.plugins} error={application.snapshot?.pluginsError}
        footerTarget={pluginFooter} beforeAction={flushDrafts} disabled={disabled} continueControl={advance("Continue to Images",undefined,"quiet")} /></Suspense>;
      primary = undefined; break;
    case "images":
      content = <GuidedImages state={application.snapshot?.images || null} error={application.snapshot?.imagesError || ""} busy={disabled}
        open={(mode) => { void action.run(async () => { await flushDrafts(); setImageView(mode); }, "", "images:open"); }}
        copy={() => { void action.run(async () => { await flushDrafts(); const result = await imagesApi.action(project.id, "edit_task"); if (!result.text) throw new Error("The image task is unavailable."); await window.dazedtl.copyText(result.text); }, "Image task copied. Paste it into your coding assistant.", "images:copy"); }}
        refresh={() => { void action.run(() => imagesApi.action(project.id, "refresh_results"), "Saved image results refreshed.", "images:refresh"); }} />;
      primary = advance("Continue to text Apply"); break;
    case "apply":
      content = <>{fileSummary()}<dl className="guided-scope-summary"><div><dt>Saved outputs</dt><dd>{outputFiles.length ? `${fileCount(outputFiles.length)} available` : "No selected outputs available"}</dd></div>
        <div><dt>Applied to game</dt><dd>{!outputFiles.length ? "No outputs ready to apply" : applied ? state.readiness.runtime_edited.some((name) => outputFiles.includes(name)) ? "Applied · later game edits retained" : "Matches saved outputs" : "Ready for application review"}</dd></div></dl>
        <p className="muted">Only selected files with saved outputs are included. Review exact destinations and replacements before Apply.</p>
        {!!state.readiness.runtime_edited.filter(name => outputFiles.includes(name)).length && <p>Later game edits are retained. Applying the saved output again replaces those edits after review.</p>}
        <ActionList>{state.readiness.publications.filter((row, index) => index === 0 || ["publishing", "recovery_needed"].includes(row.state)).map((row) => <ActionRow key={row.id} label={<><strong>{publicationLabels[row.kind] || "Text Apply"} · {row.state === "publishing" ? "Interrupted publication" : row.state === "recovery_needed" ? "Rollback needs recovery" : row.state.replaceAll("_", " ")}</strong><small>{row.files.join(", ")}</small>{["publishing", "recovery_needed"].includes(row.state) && <><small>{row.state === "publishing" ? "This batch did not finish. Some runtime files may contain the reviewed replacement." : "This batch failed, and rollback could not finish."} Preserved bytes are retained. Review restore to return this batch to its previous state; newer conflicting edits are kept.</small>{!!row.recovery_errors.length && <details><summary>Saved recovery errors</summary><ul>{row.recovery_errors.map((message, index) => <li key={index}>{message}</li>)}</ul></details>}</>}</>}>{row.state !== "restored" && task("runtime_restore", "Review restore", { publication: row.id }, !baseline)}</ActionRow>)}</ActionList>
        {state.readiness.publications.length > 1 && <details><summary>Earlier text batches</summary><ActionList>{state.readiness.publications.slice(1).filter(row => ["complete", "restored"].includes(row.state)).map(row => <ActionRow key={row.id} label={<><strong>{publicationLabels[row.kind] || "Text Apply"} · {row.state}</strong><small>{row.files.join(", ")}</small></>}>{row.state !== "restored" && task("runtime_restore", "Review restore", { publication: row.id }, !baseline)}</ActionRow>)}</ActionList></details>}
        {state.engine === "ACE" && <><p className="muted">Pack the latest JSON into native data before opening the game, including after fitting and QA edits.</p>{task("ace_pack", "Review native Ace packing", {}, !baseline || !state.aceAvailable || !state.files.length)}</>}</>;
      primary = task("export_selected", applied ? "Review Apply again" : "Review Apply", {}, !baseline || !outputFiles.length || !!changed.length, "primary", outputFiles);
      secondary = releaseButton; break;
    case "fitting":
      content = <><ActionList><ActionRow label={<><strong>Saved widths</strong><small>Dialogue {values.widths.width} · portrait {values.widths.faceWidth} · list {values.widths.listWidth} · notes {values.widths.noteWidth}</small></>}><Button disabled={disabled} onClick={() => setPanel("widths")}>Edit widths</Button></ActionRow></ActionList>
        <label className="toggle"><input type="checkbox" disabled={disabled} checked={fields.only_overflow} onChange={(event) => editForm("only_overflow", event.target.checked)} />Only rewrap text over its width limit</label>
        {fileSummary(layoutFiles.length)}
        <details><summary>Fitting coverage and row protection</summary><fieldset disabled={disabled} className="text-fitting-settings"><legend>Included text areas</legend>{([["dialogue", "Dialogue"], ["face_dialogue", "Dialogue with portrait"], ["list", "List and help descriptions"], ["notes", "Supported note patterns"]] as const).map(([key, label]) => <label className="toggle" key={key}><input type="checkbox" checked={fields.text.categories.includes(key)} onChange={event => editText("categories", event.target.checked ? [...fields.text.categories, key] : fields.text.categories.filter(value => value !== key))} />{label}</label>)}
          <label>Event codes<input value={fields.text.codes} onChange={event => editText("codes", event.target.value)} /></label><small>Supported: 122, 324, 325, 357, 401, 405. Choices (102), custom windows and arbitrary plugin text are outside this fitter.</small>
          <label className="toggle"><input type="checkbox" checked={fields.text.protect_rows} onChange={event => editText("protect_rows", event.target.checked)} />Skip protected messages that exceed the row limit</label><label>Protected row limit<input type="number" min={1} max={100} value={fields.text.max_rows} onChange={event => editText("max_rows", Number(event.target.value))} /></label></fieldset></details>
        <p className="muted">Scans current runtime files. Apply translations first to fit the translated text. Widths count characters; they do not measure rendered fonts, substitutions or window height.</p>
        {fitting && <section className="text-fit-results"><h3>Saved fitting scan</h3><ActionList><ActionRow label={<p>Eligible changes: {fitting.changes_found - fitting.overflow_skipped} · Protected overflows skipped: {fitting.overflow_skipped}</p>}>{task("rewrap_preview", "Scan again", layoutOptions, !baseline || !layoutFiles.length)}</ActionRow></ActionList>{fitting.previews.map((row, index) => <details key={index}><summary>{row.file_name} · {row.locator}{row.overflow && fields.text.protect_rows ? ` · Skipped: ${row.rows} rows exceed the protected limit` : ""}</summary><strong>Current</strong><pre>{row.before}</pre><strong>Proposed</strong><pre>{row.after}</pre></details>)}</section>}</>;
      primary = state.readiness.layout_scan && !draft.dirty && fittingSettingsSaved && !!fitting && fitting.changes_found > fitting.overflow_skipped ? task("rewrap_apply", "Review fitting Apply", layoutOptions, !baseline || !layoutFiles.length, "primary") : task("rewrap_preview", "Scan text fitting", layoutOptions, !baseline || !layoutFiles.length || !fields.text.categories.length, "primary");
      secondary = releaseButton; break;
    case "qa":
      content = <><p>Optional text QA. Prepare a saved task, copy it to your assistant, then refresh actual findings. Release remains available.</p><label>QA focus<select value={fields.text.focus} disabled={disabled} onChange={event => { editText("focus", event.target.value); editText("findings", []); }}>{[["release", "Full game text"], ["database", "Database"], ["dialogue", "Dialogue"], ["risky-codes", "Risky event codes"]].map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><ActionList><ActionRow label="Prepare or resume QA for current runtime text.">{task("qa_prepare", "Prepare text QA task", { focus: fields.text.focus }, !baseline)}</ActionRow>
        {qaTask && <ActionRow label="Paste the prepared task into your coding assistant."><ActionControl label="Copy prepared QA task" disabled={disabled} {...feedback("copy:qa", "Copying…")} onClick={() => action.run(() => window.dazedtl.copyText(String(qaTask.result!.handoff)), "QA task copied. Return to its saved findings when your assistant finishes.", "copy:qa")} /></ActionRow>}
        <ActionRow label="Read saved reports without starting an assistant.">{task("qa_status", "Refresh QA findings", { focus: fields.text.focus }, !baseline)}</ActionRow>
        <ActionRow label="Optional investigation of recurring jokes, callbacks, and terminology.">{copyTask("investigation", "Copy investigation task")}</ActionRow></ActionList>
        <p className={qa.current ? "muted" : "guided-source-alert"}>{qa.message}</p>
        {!!qaStatus.stage && <div className="guided-qa-status"><strong>Saved discovery stage: {String(qaStatus.stage).replaceAll("_", " ")}</strong>{["mechanical", "screen", "deep"].map(key => { const counts = qaStatus[key] as Record<string, number> | undefined; return counts && <p key={key}>{key === "screen" ? "Text screening" : key === "mechanical" ? "Mechanical inventory" : "Deep text review"} · {counts.accepted ?? counts.checked ?? 0} / {counts.total ?? 0}{counts.unresolved ? ` · ${counts.unresolved} unresolved` : ""}</p>; })}<small>Discovery completion describes these saved reports. It does not certify the current game as QA passed.</small>{qaJob && <Button variant="quiet" onClick={() => inspect(qaJob)}>View saved report details</Button>}</div>}
        <section className="text-qa-results"><h3>Findings and corrections</h3>{!qa.findings.length && <p className="muted">No saved findings returned.</p>}{qa.findings.map(row => <details key={row.id}><summary>{row.id} · {row.classification || row.category || row.identity || "Saved finding"}</summary><strong>Original source</strong><pre>{row.source || "Source evidence is in the saved task."}</pre><strong>Current translation</strong><pre>{row.current || row.live}</pre><p>{row.reason || row.evidence || row.note}</p></details>)}
          {qa.corrections.map((row, index) => <div className="text-qa-correction" key={row.finding_id + index}><label className="toggle"><input type="checkbox" disabled={disabled || !qa.current} checked={chosenFindings.includes(row.finding_id)} onChange={event => { editText("findings_task", qa.task || ""); editText("findings", event.target.checked ? [...new Set([...chosenFindings, row.finding_id])] : chosenFindings.filter(id => id !== row.finding_id)); }} />{row.finding_id} · {row.file}</label><strong>Before</strong><pre>{row.expected}</pre><strong>Chosen correction</strong><pre>{row.replacement}</pre></div>)}</section></>;
      primary = task("qa_apply", "Review chosen corrections", { focus: fields.text.focus, task: fields.text.findings_task, findings: chosenFindings }, !baseline || !qa.current || !chosenFindings.length, "primary"); secondary = releaseButton; break;
    case "tools": {
      const both = state.tools?.inspector.installed && state.tools.forge.installed;
      content = <><ActionList>{([['inspector', 'TL Inspector', 'Open source context from the game.'], ['forge', 'Forge', 'Edit text with the in-game overlay.']] as const).map(([key, label, description]) => <ActionRow key={key} label={<><strong>{label} <span className={state.tools?.[key].installed ? "guided-completed" : "muted"}>· {state.tools?.[key].message || "Status unavailable"}</span></strong><small>{description}</small></>}>
        <div className="guided-tool-actions">{task(key + "_install", state.tools?.[key].installed ? "Update" : "Install", {}, !baseline)}{state.tools?.[key].present && task(key + "_remove", "Remove", {}, !baseline)}</div></ActionRow>)}
        <ActionRow label={<><strong>Tool settings</strong><small>Saved: Inspector {release.tools.hotkey} · Forge {release.tools.forgeHotkey} · scale {release.tools.uiScale === "auto" ? "Auto" : Number(release.tools.uiScale) * 100 + "%"}</small></>}><Button disabled={disabled} onClick={() => setPanel("tools")}>Configure tools</Button></ActionRow>
        <ActionRow label="Create a portable player walkthrough with your coding assistant.">{copyTask("walkthrough", "Copy walkthrough task")}</ActionRow></ActionList></>;
      primary = <Button onClick={() => textView("apply")}>Back to Apply & Fitting</Button>; secondary = releaseButton; break;
    }
    case "package":
      content = <ReleaseContent value={release} disabled={disabled} artifact={artifact}
        unapplied={state.readiness.unapplied} apply={<ActionControl label="Open Apply" disabled={disabled} {...feedback("release:apply", "Opening Apply…")}
          onClick={() => action.run(async () => { editText("view", "apply"); await navigate("apply", "apply"); }, "", "release:apply")} />}
        edit={change => form.session.edit(current => ({ ...current, release: { ...current.release, ...change } }))}
        chooseFolder={() => chooseFolder("release")} assets={() => setPanel("release-assets")}
        inspect={<ActionControl label="View files & exclusions" disabled={disabled || !release.directory || !release.name || !!state.readiness.unapplied.length}
          {...feedback("package:inspect", "Reading archive contents…")} onClick={() => action.run(async () => {
            await save(); setInspectRelease(true); setPreview(await api.preview(project.id, releaseAction, undefined, { output: releasePath }));
          }, "", "package:inspect")} />}
        open={<ActionControl label="Open release folder" disabled={!artifact?.available || action.busy} {...feedback("open-release", "Opening…")}
          onClick={() => action.run(() => window.dazedtl.openFolder("output", artifact!.folder), "Release folder opened.", "open-release")} />}
        packing={state.engine === "ACE" ? <><p className="muted">{state.acePacking.message}</p>
          {!state.aceAvailable && !state.acePacking.current && <p>Native packing requires a supported Windows environment.</p>}
          {task("ace_pack", state.acePacking.current ? "Review native packing again" : "Review native Ace packing", {}, !baseline || !state.aceAvailable || !state.files.length)}</> : undefined} />;
      primary = task(releaseAction, release.kind === "game" ? "Build clean game ZIP" : "Review & build patch ZIP", { output: releasePath },
        !baseline || !release.directory.trim() || !release.name.trim() || /[\\/]/.test(release.name) || !state.acePacking.current || !!state.readiness.unapplied.length, "primary"); break;
    default:
      content = job ? <RunPanel projectId={project.id} hideTitle job={job} active={running && ["running", "waiting"].includes(job.status)} busy={action.busy || running && job.status === "failed"}
        pendingKey={action.busy ? action.key : ""} error={action.key.startsWith("run:") ? action.error : ""}
        stop={() => action.run(() => api.stop(project.id, job.id), "", "run:stop")} resume={() => setResume(job)} answer={(approved) => action.run(() => api.answer(project.id, job.approval!.token, approved), "", "run:answer:" + approved)}
        exportFiles={() => action.run(async () => setOutput((await api.export(project.id)).path), "Output copy saved.", "run:export")} /> : <p className="muted">No saved translation run is available for this game.</p>;
      primary = job?.status === "complete" && job.mode !== "estimate"
        ? job.mode === "speakers" ? <Button variant="primary" onClick={() => stepTask("guidance")}>Review translation guidance</Button> : nextRun(job)
        : <Button onClick={() => stepTask(stage.tasks[0].id)}>Return to tasks</Button>;
      secondary = job?.status === "complete" && job.mode !== "estimate" && job.mode !== "speakers" && job.outputsAvailable ? applyRun(job) : undefined;

  }
  const previous = taskIndex > 0 ? stage.tasks[taskIndex - 1] : stages[stages.indexOf(stage) - 1]?.tasks.at(-1);
  const paid = preview?.action === "start" && preview.options.mode !== "estimate";
  const reviewEstimateCurrent = !paid || preview?.options.mode === "speakers" || !!preview?.estimate && currentEstimate(preview.options.phase as Phase)?.id === preview.estimate.jobId;
  const savePanel = (label = "Save & close") => <ActionControl label={label} variant="primary" disabled={disabled} {...feedback("save-options", "Saving…")} onClick={() => action.run(async () => { await save(); setPanel(null); }, "Options saved.", "save-options")} />;
  if (imageView && taskId === "images") {
    if (editorAssets) return <ImageTextEditor projectId={project.id} assetIds={editorAssets} observationKey={application.snapshot} onClose={() => setEditorAssets(null)} />;
    return <ImageManager projectId={project.id} initialMode={imageView} observed={application.snapshot?.images}
      onClose={() => setImageView(null)} onOpenEditor={(ids, mode) => { setImageView(mode || imageView); setEditorAssets(ids); }} />;
  }
  return <PageLayout variant="editor" className={`guided-workspace${taskId === "main-text" ? " translate-redesign" : ""}`} aria-label="Translation workspace">
    <PageHeader className="guided-header" title="Translation" description={state.engine === "ACE" ? "RPG Maker VX Ace" : "RPG Maker MV / MZ"}
      actions={<div className="actions"><Button variant="quiet" onClick={() => setPanel("project-tools")}>Project tools</Button><Button variant="quiet" onClick={() => setHistory(true)}>History</Button><Button variant="quiet" onClick={() => action.run(() => window.dazedtl.openFolder("project"), "Game folder opened.", "open-game")}><FolderOpen size={16} />Game folder</Button></div>} />
    <div className="guided-layout">
      <WorkflowNavigation stages={stages} step={position.step} completed={completed} disabled={action.busy} move={move} taskFor={stage => taskForStage(state, stage)} />
      <div className="guided-task-workspace">
        {unfinished && taskId !== "main-text" && taskId !== "run" && !["prepare", "context"].includes(position.step) && <div className="guided-attention"><span>{job?.mode === "speakers" ? "Saved name translation" : "Saved translation run"} · {job?.status}</span><Button onClick={() => move(runStage(state), "run")}>Open saved run</Button></div>}
        {activeOperation && !localOperation && <div className="guided-attention"><JobStatus compact job={{ ...activeOperation, label: activeOperation.label || "Current operation" }} /><Button disabled={action.busy} onClick={() => stopOperation(activeOperation)}>Stop operation</Button></div>}
        <PageBody ref={bodyRef} className={`guided-task-body${taskId === "plugins" ? " plugin-task-body" : ""}`}>
          <div className="guided-task-heading"><div className="guided-task-location"><span>{stage.title}{taskId === "plugins" ? "" : taskIndex >= 0 ? ` · Task ${taskIndex + 1} of ${stage.tasks.length}` : " · Saved run"}</span><Button variant="quiet" onClick={() => setPanel("tasks")}>All tasks</Button></div>
            <h2 ref={headingRef} tabIndex={-1}>{taskId === "apply" && taskView === "qa" ? "Text QA · optional" : taskId === "apply" && taskView === "tools" ? "Game tools · optional" : selectedTask?.title || phaseLabels[runPhase(state)] + " run"}</h2>{selectedTask?.description && <p>{selectedTask.description}</p>}{taskId === "other-event-text" && <p className="muted">{{audit: "Investigation", sources: "Findings & source choices", "advanced-run": "Translation", variables: "Comparison updates"}[state.eventText.view]}</p>}</div>
          <Message message={!preview && (!feedbackKeys.has(action.key) && !(taskId === "run" && action.key.startsWith("run:"))) ? action.error : ""} onDismiss={action.clear} />
          <Message message={state.collectionError} />
          {changed.length > 0 && ["translate", "advanced", "apply", "review"].includes(position.step) && <div className="guided-source-alert"><p>{fileCount(changed.length)} have changed sources. Review them before new work.</p>{task("refresh_sources", "Review source refresh", {}, unfinished || !baseline, "default", changed)}</div>}
          {baselineNotice && taskId === "names" && <p className="guided-success" role="status">{baselineNotice}</p>}
          {taskId === "apply" && <div className="text-workspace-nav"><div role="group" aria-label="Apply and Fitting views">{(["apply", "fitting"] as const).map(view => <Button key={view} aria-pressed={taskView === view} disabled={disabled} onClick={() => textView(view)}>{view === "apply" ? "Apply" : "Fitting"}</Button>)}</div><div className="actions"><Button variant="quiet" aria-pressed={taskView === "qa"} disabled={disabled} onClick={() => textView("qa")}>Text QA · optional</Button>{state.engine === "MVMZ" && <Button variant="quiet" aria-pressed={taskView === "tools"} disabled={disabled} onClick={() => textView("tools")}>Tools · optional</Button>}</div></div>}
          {content}
          {output && <p className="path">Output copy: {output} <Button onClick={() => action.run(() => window.dazedtl.openFolder("output", output))}>Open folder</Button></p>}
        </PageBody>
        {taskId === "plugins" ? <div className="plugin-host-footer" ref={setPluginFooter} /> : <ActionBar feedback={<div className="guided-footer-context">{previous && <Button variant="quiet" disabled={action.busy} onClick={() => stepTask(previous.id)}>Back</Button>}<span className={backupPending || preparationPending ? "guided-prepare-feedback" : undefined}>{backupPending ? "Backup in progress" : preparationPending ? "Preparation in progress" : taskId === "format" && (preparationComplete || baseline) ? "Game files prepared" : draft.dirty ? "Options retained for recovery" : preserved ? "Original preserved" : "Start by preserving the original"}</span></div>}>
          {secondary}{primary}
        </ActionBar>}
      </div>
    </div>
    {panel && <Modal label={panel === "files" ? "Choose files for this pass" : panel === "tasks" ? "Translation tasks" : "Translation options"} className="guided-sheet" dismissible={!action.busy} onDismiss={closePanel}>
      <header className="guided-sheet-heading"><h2>{{ tasks: "Translation tasks", files: "Choose files for this pass", backups: "Backups & recovery", versions: "Game updates", speakers: "Speaker detection", widths: "Measured line widths", options: "Engine options & source refresh", "translation-context": "Guidance & layout", tools: "Configure playtest tools", "project-tools": "Project tools", references: "Reference translations", preparation: "Preparation tools", exclusions: "Release exclusions", "release-assets": "Additional runtime assets" }[panel]}</h2></header>
      {panel === "files" ? <FileSelection state={{ ...state, files: pickerFiles }} selected={pickerSelected} change={(names) => edit("selected", fileScope ? retainOtherScope(values.selected, pickerFiles, names) : names)} disabled={disabled} /> : <div className="guided-sheet-body">
        {panel === "tasks" && <div className="guided-all-tasks">{stages.map((item) => <section key={item.id}><h3>{item.title}</h3>{item.tasks.map((entry) => <Button key={entry.id} variant="quiet" onClick={() => move(item.id, entry.id)}>{entry.title}</Button>)}</section>)}</div>}
        {panel === "project-tools" && <ActionList>
          <ActionRow label={<><strong>Move to a newer game release</strong><small>Bring a developer’s update into the game you’re translating.</small></>}><Button onClick={() => setPanel("versions")}>Game updates</Button></ActionRow>
          <ActionRow label={<><strong>Save or recover files</strong><small>Manage backups and recover an earlier copy when you need one.</small></>}><Button onClick={() => setPanel("backups")}>Backups & recovery</Button></ActionRow>
        </ActionList>}
        {panel === "backups" && backups?.(utilityActions)}{panel === "versions" && versions?.({ backups: () => setPanel("backups"), prepare: () => stepTask("baseline"), checkpoint: () => { setPanel(null); void review("checkpoint"); }, target: utilityActions })}
        {panel === "speakers" && <>{speakersConfigured ? <SpeakerFindings findings={findings} values={values.engine_options} /> : speakerStatus}
          <details open={!speakersConfigured}><summary>Adjust manually</summary><p className="muted">Your overrides are retained. Recollect names after changing detection.</p>
            <EngineOptions state={state} values={values.engine_options} keys={speakers} disabled={disabled} change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} />
            {!!findings.overrides.length && <ActionControl label="Use investigation recommendations" disabled={disabled || draft.dirty || !!state.optionsDraft} pending={speakerAction.busy} pendingText="Applying rules…" error={speakerAction.error} notice={speakerAction.notice}
              onClick={() => speakerAction.run(() => draft.applySpeakers(true), "Investigation recommendations restored.", "apply")} />}
          </details></>}
        {panel === "widths" && <>{widths}{copyTask("wrap", "Copy width-measurement task")}</>}
        {panel === "options" && <><EngineOptions state={state} values={values.engine_options} keys={["IGNORETLTEXT", "PRESERVEORIGINAL", "FIXTEXTWRAP", "BRFLAG", "TLSYSTEMVARIABLES", "TLSYSTEMSWITCHES"]} disabled={disabled} change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} />
          <Section title="Start a new source pass"><p className="muted">Refresh archives selected working copies, outputs, and variable cache. Frozen runs retain their original records.</p>{task("refresh_sources", "Review selected source refresh", {}, !baseline || !values.selected.length, "default", values.selected)}</Section></>}
        {panel === "preparation" && <ActionList>{formatActions.map((item) => <ActionRow key={item.id} label={item.hint}>{task(item.id, (item.id === "gameupdate" ? "Recreate GameUpdate files" : "Rerun " + item.title.toLowerCase()), {}, !preserved)}</ActionRow>)}</ActionList>}
        {panel === "tools" && <><p className="muted">Settings are saved with this project. Install/update a plugin or apply settings to use them in the game.</p><fieldset disabled={disabled}><div className="guided-widths">{([["hotkey", "TL Inspector hotkey"], ["forgeHotkey", "Forge hotkey"]] as const).map(([key, label]) => <label key={key}>{label}<input value={release.tools[key]} onChange={(event) => editRelease("tools", { ...release.tools, [key]: event.target.value })} /></label>)}</div>
          <FieldRow id="guided-tool-scale" label="Overlay scale">{(props) => <select {...props} value={release.tools.uiScale} onChange={(event) => editRelease("tools", { ...release.tools, uiScale: event.target.value })}>{["auto", "1", "1.25", "1.5", "1.75", "2", "2.25", "2.5"].map((value) => <option key={value} value={value}>{value === "auto" ? "Automatic" : Number(value) * 100 + "%"}</option>)}</select>}</FieldRow>
          <FieldRow id="guided-tool-editor" label="Source editor" help="Use auto for detection, or choose the editor executable.">{(props) => <div className="guided-folder-field"><input {...props} value={release.tools.editorCmd} onChange={(event) => editRelease("tools", { ...release.tools, editorCmd: event.target.value })} /><Button onClick={() => action.run(async () => { const path = await window.dazedtl.chooseEditor(); if (path) editRelease("tools", { ...release.tools, editorCmd: path }); }, "", "choose-editor")}>Choose editor</Button></div>}</FieldRow></fieldset>
          {task("editors", "Find installed editors")}{operationJob("editors")?.result && <pre>{JSON.stringify(operationJob("editors")!.result, null, 2)}</pre>}
          <Section title="Installed plugins">{task("playtest_apply", "Apply settings to game", {}, !baseline || !state.tools?.inspector.installed && !state.tools?.forge.installed)}</Section></>}
        {panel === "references" && <ReferenceTools state={state} disabled={disabled} action={action} save={save} review={review} />}
        {panel === "release-assets" && <><p>Applied images and tracked runtime assets are already included. Add other player images or fonts by exact game-relative path, one per line.</p>
          <label>Image and font paths<textarea rows={7} value={release.assets.join("\n")} disabled={disabled}
            onChange={event => editRelease("assets", event.target.value.split("\n"))} /></label>
          <p className="muted">Use img/ or fonts/, including www/ layouts. Private files, missing files and symbolic links are rejected. Build reviews the exact current bytes.</p>
          <ActionControl label="Save runtime assets" variant="primary" disabled={disabled} {...feedback("release-assets:save", "Saving…")}
            onClick={() => action.run(async () => { const names = release.assets.map(name => name.trim()).filter(Boolean); editRelease("assets", [...new Set(names)]); await flushDrafts(); await save(); setPanel(null); }, "Runtime assets retained.", "release-assets:save")} /></>}

      </div>}
      {panel === "translation-context" && <div className="guided-sheet-body"><ActionList>
        <ActionRow label={<><strong>Translation guidance</strong><small>Saved glossary, names, terminology and game context.</small></>}><Button onClick={() => { setPanel(null); stepTask("guidance"); }}>Review guidance</Button></ActionRow>
        <ActionRow label={<><strong>Text layout</strong><small>Current character limits for dialogue and interface text.</small></>}><Button onClick={() => setPanel("widths")}>Review layout</Button></ActionRow>
        <ActionRow label={<><strong>Engine options</strong><small>Choose text sources and parsing settings for new runs.</small></>}><Button onClick={() => setPanel("options")}>Engine options</Button></ActionRow>
      </ActionList></div>}
      <ActionBar feedback={<Message message={action.error && !feedbackKeys.has(action.key) ? action.error : ""} />}>{panel === "files" ? <><Button disabled={action.busy} onClick={closePanel}>Cancel</Button><ActionControl label={`Use ${fileCount(pickerSelected.length)}`} variant="primary" disabled={disabled} {...feedback("files:save", "Saving selection…")} onClick={() => action.run(async () => { await save(); setPanel(null); }, "File selection saved.", "files:save")} /></> : <><Button disabled={action.busy} onClick={() => setPanel(null)}>Close</Button><div ref={setUtilityActions} className="action-bar-slot" />{["speakers", "widths", "options", "tools"].includes(panel) && (panel !== "speakers" || draft.dirty) && <>{draft.dirty && <ActionControl label="Discard engine options" disabled={disabled} {...feedback("discard-options", "Discarding…")} onClick={() => action.run(draft.discard, "Engine options restored.", "discard-options")} />}{savePanel()}</>}</>}</ActionBar>
    </Modal>}
    {history && <Modal label="Recent activity" onDismiss={() => setHistory(false)}><h2>Recent activity</h2><ActivityHistory state={state} translation={translation} inspect={inspect} /><Button onClick={() => setHistory(false)}>Close</Button></Modal>}
    {inspected && <Modal label="Request inspector" className="request-inspector-sheet" onDismiss={() => setInspected(null)}><div className="request-inspector-heading"><h2>{inspected.process ? "Requests" : inspected.label || "Saved activity"}</h2><Button onClick={() => setInspected(null)}>Close</Button></div>
      {inspected.keptForHistory && <p>Kept failed run. Its original parameters, requests, and provider history are unchanged. This record does not resume the run.</p>}
      <ProcessPanel compact job={inspected} readPayload={index => api.guided.payload(project.id, inspected.id, index)}
        readProvider={() => api.guided.providerDetails(project.id, inspected.id)} />
      {inspected.files && <p>{fileCount(inspected.files.length)} frozen · {inspected.model} · {inspected.mode}</p>}
      <Message message={action.key === "inspect:" + inspected.id ? action.error : ""} />
      {inspected.result && <pre>{JSON.stringify(inspected.result, null, 2)}</pre>}
      {!inspected.process && !!inspected.log.length && <details><summary>Diagnostic log</summary><pre>{inspected.log.join("\n")}</pre></details>}
      {inspected.status === "complete" && Object.keys(inspected.outputs || {}).length > 0 && <ActionControl label="Save this run’s output copy" disabled={action.busy || inspected.outputsAvailable === false} {...feedback("run:export", "Saving output copy…")} onClick={() => action.run(async () => setOutput((await api.export(project.id, inspected.id)).path), "Output copy saved.", "run:export")} />}
      </Modal>}
    {preview && <Modal label={preview.action === "git_setup" ? "Review version baseline" : preview.action === "release_patch" ? inspectRelease ? "Archive contents" : "Review patch ZIP" : preview.action === "release" ? inspectRelease ? "Archive contents" : "Replace game ZIP" : "Review translation action"} className={`guided-sheet${preview.action === "git_setup" ? " guided-baseline-review" : ["release", "release_patch"].includes(preview.action) ? " guided-release-review" : ""}`} dismissible={!action.busy} onDismiss={() => setPreview(null)}><header className="guided-sheet-heading"><h2>{["release", "release_patch"].includes(preview.action) ? inspectRelease ? "Archive contents" : preview.action === "release_patch" ? "Review patch ZIP" : "Replace game ZIP" : preview.label}</h2></header><div className="guided-sheet-body">
      {["release", "release_patch"].includes(preview.action) && <ReleaseReview preview={preview} inspectOnly={inspectRelease} busy={action.busy} editAssets={() => { setPreview(null); setPanel("release-assets"); }} />}
      {preview.action === "git_setup" ? <><p>Check the version, original source and runtime files before saving.</p>
        <dl className="guided-baseline-summary"><div><dt>Game version</dt><dd>{String(preview.options.version)}</dd></div>
          <div><dt>Original source</dt><dd>{preview.options.untranslated ? `This untranslated game, after preparation: ${preview.destination}` : String(preview.options.original)}</dd></div></dl>
      </> : !["release", "release_patch"].includes(preview.action) && <p className="path">{preview.destination}</p>}{preview.action === "start" && <p>Phase: {phaseLabels[preview.options.phase as Phase]}</p>}
      {!["release", "release_patch"].includes(preview.action) && !!preview.paths.length && <><p>{fileCount(preview.files || preview.paths.length)} {preview.action === "git_setup" ? "in this baseline" : "in this action"}</p>{preview.paths.length <= 8 ? <ul className="guided-preview-paths" aria-label="Files in this action">{preview.paths.map((name) => <li key={name} className="guided-preview-path">{name}</li>)}</ul> : <div className="guided-preview-files"><VirtualList items={preview.paths} itemKey={pathKey} label="Files in this action" empty={null}>{(name) => <div className="guided-preview-path">{name}</div>}</VirtualList></div>}</>}
      {!!preview.additions?.length && <p>{preview.additions.length} files are additions to the original baseline.</p>}
      {preview.action === "backup_source" && sourceBackup?.available === false && <p>This saves current files. It cannot recover the missing original.</p>}
      {preview.action === "refresh_sources" && <p>Archive these files’ working copies, outputs, and variable cache before refreshing from the original source. Frozen provider runs remain retained.</p>}
      {preview.action === "export_selected" && <p>Apply accumulated translated outputs to these runtime files.</p>}
      {preview.action === "runtime_restore" && <p>Return these files to the preserved bytes from before the chosen batch. Review the current and restored text below before continuing.</p>}
      {preview.publication && <><p>The whole batch is checked before publication. Exact before/after backups are retained; failure attempts rollback. Restore requires another review and rejects newer conflicting edits.</p>{preview.publication.map(row => <details className="text-publication" key={row.path}><summary>{row.path} · {row.size.toLocaleString()} bytes{row.later_edits ? " · Replaces later game edits" : ""}</summary><p className="path">{row.destination}</p><small>Current SHA-256 {row.before}<br />Candidate SHA-256 {row.after}</small><strong>Runtime changes{row.truncated ? " (diff exceeds 16,000 characters)" : ""}</strong><pre>{row.diff || "Runtime bytes already match this candidate."}</pre><details><summary>JSON context</summary><strong>Current runtime JSON (first 16,000 characters)</strong><pre>{row.before_text}</pre><strong>Reviewed replacement JSON (first 16,000 characters)</strong><pre>{row.after_text}</pre></details></details>)}</>}
      {paid && preview.estimate && <section aria-label={reviewEstimateCurrent ? "Matching estimate" : "Previous estimate"}><h3>{reviewEstimateCurrent ? "Matching estimate" : "Previous estimate"}</h3><Estimate value={preview.estimate.value} /><p className="muted">{reviewEstimateCurrent ? "Selection, source, pricing, guidance, and layout match this estimate." : "This quote was calculated before the reviewed inputs changed."}</p></section>}
      {paid && !reviewEstimateCurrent && <div role="alert"><p>Estimate needs refreshing. Reviewed inputs changed.</p><Button disabled={disabled} onClick={() => { const target = preview.options.phase; setPreview(null); void review("start", { mode: "estimate", phase: target }); }}>Refresh estimate</Button></div>}
      {paid && <p>{preview.run?.connection || state.provider.connection} · {preview.run?.model || state.provider.model} · {preview.options.mode === "batch" ? "Prepare this scope for a separate Batch cost approval. Speaker translation can request its own approval." : "API requests may incur charges using this run’s frozen settings."}</p>}
      {paid && preview.options.phase === "advanced" && <><p>Selected sources: {enabledCodes.join(", ")}</p>{values.engine_options.CODE122 === true && <p>Variable IDs: {String(values.engine_options.CODE122_VAR_RANGES)}</p>}{values.engine_options.CODE357 === true && <p>Plugin handlers: {(values.engine_options.ENABLED_PLUGINS_357 as string[] || []).join(", ") || "None"}</p>}{values.engine_options.CODE355655 === true && <p>Script patterns: {(values.engine_options.ENABLED_PATTERNS_355655 as string[] || []).join(", ") || "None"}</p>}</>}
      {paid && preview.options.phase === "advanced" && <><p>{state.eventText.manual.length ? "Manual overrides: " + state.eventText.manual.join(", ") + ". Reason: " + state.eventText.manualReason : "Source choices match reviewed investigation recommendations."}</p>{state.eventText.rows.filter((row) => values.engine_options[row.key]).map((row) => <details key={row.key}><summary>{row.label} · Actual coverage</summary><p>{row.coverage}</p>{!!row.builtins.length && <p>Built-ins also enabled: {row.builtins.join(", ")}</p>}</details>)}</>}
      {paid && preview.options.phase === "advanced" && values.engine_options.AUTONAMEPOPUP101 === true && <p>Saved AutoNamePopup handling also processes supported actor-name changes independently of source 320.</p>}
      {paid && preview.options.phase === "variables" && <p>Reviewed literal-based updates apply to all matching quoted literals in the selected code-111 expressions. Unmatched literals remain unchanged.</p>}
      {preview.rewrap && <><p>{preview.rewrap.changes_found} fitting changes · {preview.rewrap.overflow_skipped} protected overflows skipped</p>{preview.rewrap.previews.map((row, index) => <details key={index}><summary>{row.file_name} · {row.locator}</summary><strong>Before</strong><pre>{row.before}</pre><strong>After</strong><pre>{row.after}</pre></details>)}</>}
      </div><ActionBar feedback={<Message message={action.error} />}><Button disabled={action.busy} onClick={() => setPreview(null)}>{inspectRelease ? "Close" : preview.action === "git_setup" ? "Back" : "Cancel"}</Button>{!inspectRelease && <Button variant="primary" disabled={!reviewEstimateCurrent} pending={action.busy} onClick={() => action.run(() => execute(preview), "", actionKey(preview.action, preview.options))}>
        {preview.publication ? preview.action === "runtime_restore" ? "Restore reviewed batch" : "Apply reviewed batch" : preview.action === "git_setup" ? "Save baseline & continue" : paid && preview.options.mode === "translate" ? "Approve and start Live API" : paid && preview.options.mode === "batch" ? "Prepare Batch for cost review" : preview.action === "refresh_sources" ? "Archive and refresh sources" : ["release", "release_patch"].includes(preview.action) ? `${preview.overwrite ? "Replace & build" : "Build"} ${preview.action === "release_patch" ? "patch" : "game"} ZIP` : "Run this action"}</Button>}</ActionBar></Modal>}
    {state.eventText.picker && <EventTextPicker key={state.eventText.picker.key} projectId={project.id} state={state.eventText} initial={state.eventText.picker} save={saveSourcePicker} refresh={application.refresh} />}
    {sourceReview && <EventTextReview review={sourceReview} busy={action.busy} error={action.error} cancel={() => setSourceReview(null)} accept={(reason, accepted) => action.run(async () => {
      await api.guided.eventTextReview(project.id, sourceReview.revision, sourceReview.state.binding, sourceReview.state.reportId, reason, accepted);
      setSourceReview(null); await api.guided.eventTextView(project.id, "advanced-run");
    }, "Source choices reviewed. Estimate this scope before paid review.", "event-text:confirm")} />}
    {comparisonReview && <Modal label="Review comparison coverage" className="guided-sheet" dismissible={!action.busy} onDismiss={() => setComparisonReview(false)}>
      <header className="guided-sheet-heading"><h2>Review matching comparisons</h2></header><div className="guided-sheet-body"><p>Mappings are keyed by literal text, not variable ID. The engine updates every matching quoted literal in these selected code-111 expressions. A saved mapping does not prove a logic string is safe to translate.</p>
        <p>{state.comparisons.matches} matched · {state.comparisons.unmatched} unmatched literals will remain unchanged.</p>
        {state.comparisons.rows.map((row, index) => <section className="event-text-source" key={index}><strong>{row.file} · {row.location}</strong><p>Variable IDs: {row.variables.join(", ") || "Dynamic or unresolved - inspect the full expression"}</p><p>{row.literal} → {row.translation}</p></section>)}
        <label className="toggle"><input type="checkbox" checked={comparisonsAccepted} onChange={(event) => setComparisonsAccepted(event.target.checked)} />I checked every matched use, including internal references and logic, and accept these literal-based updates.</label>
      </div><ActionBar feedback={<Message message={action.error} />}><Button disabled={action.busy} onClick={() => setComparisonReview(false)}>Cancel</Button><Button variant="primary" disabled={!comparisonsAccepted || !state.comparisons.matches} pending={action.busy} onClick={() => action.run(async () => { await save(); await api.guided.comparisonsReview(project.id, state.comparisons.fingerprint, true); setComparisonReview(false); }, "Comparison coverage reviewed.", "event-text:comparisons")}>Confirm comparison coverage</Button></ActionBar>
    </Modal>}
    {resume && <Modal label="Resume saved run" dismissible={!action.busy} onDismiss={() => setResume(null)}><h2>Resume the saved run?</h2><p>{resume.model} · {fileCount(resume.files?.length || 0)} · saved run settings</p><p>{resume.mode === "batch" && resume.phase?.startsWith("poll") ? "Continue monitoring this submitted Batch and save its results when ready." : "Continue its frozen files, context, and provider settings. Remaining requests may incur charges."}</p><Message message={action.key === "run:resume" ? action.error : ""} /><div className="actions"><Button disabled={action.busy} onClick={() => setResume(null)}>Cancel</Button><Button variant="primary" pending={action.busy} onClick={() => action.run(async () => { await api.resume(project.id, resume.id); setResume(null); }, "", "run:resume")}>Resume saved run</Button></div></Modal>}
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
