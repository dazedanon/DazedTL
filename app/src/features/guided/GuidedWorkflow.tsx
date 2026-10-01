import { useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Clipboard, FolderOpen } from "lucide-react";
import { api } from "../../api/client";
import type { GuidedOptions, GuidedState, GuidedStep, Phase, Preview, Project, TranslationState } from "../../api/contracts";
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
import RunPanel from "./RunPanel";
import { FileSelection } from "./FileSelection";
import { EngineOptions } from "./EngineOptions";
import { useGuidedWorkflow } from "./useGuidedWorkflow";

const steps: { id: GuidedStep; label: string }[] = [
  { id: "prepare", label: "Prepare" }, { id: "context", label: "Context" },
  { id: "translate", label: "Translate" }, { id: "apply", label: "Apply" },
  { id: "layout", label: "Layout" }, { id: "review", label: "Review & release" },
];
const speakers = ["NAMES", "FIRSTLINESPEAKERS", "INLINE401SPEAKERS", "FACENAME101", "AUTONAMEPOPUP101", "SPEAKERS408"];
const advanced = ["CODE122", "CODE122_VAR_RANGES", "CODE357", "CODE355655", "CODE657", "CODE356", "CODE320", "CODE324", "CODE325", "CODE108", "ENABLED_PLUGINS_357", "ENABLED_PATTERNS_355655"];
const phases: [Phase, string][] = [["database", "1. Database text and names"], ["dialogue", "2. Dialogue and choices"], ["variables", "3. Variable comparison cache"], ["advanced", "4. Reviewed advanced text"]];

export default function GuidedWorkflow({ project, settings, direct = false, openGuide, backups }: {
  project: Project; settings: () => void; direct?: boolean; openGuide?: () => void; backups?: ReactNode;
}) {
  const application = useApplication();
  const state = application.snapshot?.guided;
  const translation = application.snapshot?.translation;
  if (!state || state.projectId !== project.id || !translation || translation.projectId !== project.id)
    return <Message message={application.snapshot?.translationError || "Open the game's Guided Workflow to continue."} />;
  return <Workspace key={project.id} project={project} state={state} translation={translation}
    settings={settings} direct={direct} openGuide={openGuide} backups={backups} />;
}

function Workspace({ project, state, translation, settings, direct, openGuide, backups }: {
  project: Project; state: GuidedState; translation: TranslationState; settings: () => void;
  direct: boolean; openGuide?: () => void; backups?: ReactNode;
}) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const draft = useGuidedWorkflow(state, action.report);
  const values = draft.value.values;
  const [preview, setPreview] = useState<Preview | null>(null);
  const [resume, setResume] = useState(false);
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
  const step = direct ? "translate" : state.step;
  const stepIndex = steps.findIndex((item) => item.id === step);
  const running = !!application.snapshot?.application.running;
  const disabled = action.busy || draft.committing || running;
  const preserved = !!translation.lifecycle.source_backup;
  const baseline = preserved && !!translation.git?.configured;
  const edit = <K extends keyof GuidedOptions>(key: K, value: GuidedOptions[K]) =>
    draft.session.edit((current) => ({ ...current, values: { ...current.values, [key]: value } }));
  const save = async () => { await flushDrafts(); if (draft.dirty || state.optionsDraft) await draft.save(); };
  const move = (next: GuidedStep) => action.run(async () => {
    await flushDrafts();
    await api.guided.position(project.id, next);
  });
  const review = (name: string, options: Record<string, unknown> = {}, files?: string[]) => action.run(async () => {
    await save();
    const result = await api.preview(project.id, name, files, options);
    if (!result.confirmation) await api.execute(project.id, result.token);
    else setPreview(result);
  });
  const copySkill = (name: string) => action.run(async () => {
    await save();
    await window.dazedtl.copyText((await api.guided.skill(project.id, name)).text);
  }, "Task instructions copied. Review the result here when your assistant finishes.");
  const task = (name: string, label: string, options: Record<string, unknown> = {}, blocked = false) =>
    <Button disabled={disabled || blocked} onClick={() => review(name, options)}>{label}</Button>;
  const filePicker = <>
    <FileSelection state={state} selected={values.selected} disabled={disabled} change={(names) => edit("selected", names)} />
    <Button variant="primary" disabled={disabled || !preserved || !values.selected.length}
      onClick={() => review("import", {}, values.selected)}>Import selected files</Button>
    <p className="muted">Import copies the selection into this project's work area. Start with the database and one early map, then expand after a playtest.</p>
  </>;
  const latest = state.operations[0];
  const sharedJob = translation.jobs[0];
  const job = state.run;
  const layoutOptions = { files: state.importedFiles, widths: values.widths, categories: ["dialogue", "face_dialogue", "list", "notes"], codes: "401,405", max_rows: 4, protect_rows: true, over_limit: onlyOverflow };
  const paid = preview?.action === "start" && preview.options.mode !== "estimate";

  return <PageLayout className="guided-workspace" aria-label={direct ? "Manual translation" : "Guided workflow"}>
    <PageHeader title={direct ? "Translate files" : "Guided Workflow"} divided
      description={project.name + " · " + (state.engine === "ACE" ? "RPG Maker VX Ace" : "RPG Maker MV / MZ")}
      actions={<Button onClick={() => action.run(() => window.dazedtl.openFolder("project"))}><FolderOpen size={16} />Game folder</Button>} />
    {!direct && <nav className="steps" aria-label="Guided steps">
      {steps.map((item, index) => <Button key={item.id} aria-current={step === item.id ? "step" : undefined}
        disabled={action.busy} onClick={() => move(item.id)}><span>{index + 1}</span>{item.label}</Button>)}
    </nav>}
    <Message message={action.error} onDismiss={action.clear} />
    <Message message={state.collectionError} />
    {action.notice && <p role="status">{action.notice}</p>}
    {draft.dirty && <div className="guided-save-bar">
      <span className="muted">Unsaved workflow options · draft retained for recovery</span>
      <Button disabled={disabled} onClick={() => action.run(save)}>Save options</Button>
      <Button disabled={disabled} onClick={() => action.run(draft.discard)}>Discard changes</Button>
    </div>}

    {step === "prepare" && <>
      <Section title="Preserve the original" hint={preserved ? "Backup saved" : "Start here"}>
        <p className="muted">Save a recoverable copy before formatting or changing the game.</p>
        {task("backup_source", "Back up original game", {}, preserved)}
        {translation.lifecycle.source_backup && <p className="muted">{translation.lifecycle.source_backup.files.toLocaleString()} files preserved.</p>}
      </Section>
      {state.engine === "ACE" && <Section title="Extract Ace data">
        <p className="muted">Decrypt the archive if needed, then convert native data with Sinflower's RV2JSON. The exported JSON uses the same translation phases as MV/MZ.</p>
        {!state.aceAvailable && <p className="banner">These tools need Windows or Wine. Existing ace_json exports can still be used here.</p>}
        <div className="actions">
          {task("ace_decrypt", "Decrypt game archive", {}, !preserved || !state.encrypted.length || !state.aceAvailable)}
          {task("ace_extract", "Convert native data to JSON", {}, !preserved || !state.aceAvailable)}
        </div>
      </Section>}
      <Section title="Prepare game files">
        <p className="muted">Run these before establishing the original Git baseline. Each action shows a preview before changing files.</p>
        <div className="guided-tasks">
          <div><strong>1. Format game data</strong>{task("format_data", "Format JSON files", {}, !preserved || !state.files.length)}</div>
          {state.hasPlugins && <div><strong>2. Format plugin configuration</strong>{task("format_plugins", "Format plugins.js", {}, !preserved)}</div>}
          <div><strong>{state.hasPlugins ? "3" : "2"}. Install GameUpdate</strong>{task("gameupdate", "Create GameUpdate files", {}, !preserved)}</div>
        </div>
      </Section>
      <Section title="Set up Git versioning" hint={translation.git?.configured ? "Configured" : "Original and translation branches"}>
        <fieldset disabled={disabled}>
          <FieldRow id="guided-version" label="Game version">{(props) => <input {...props} value={version} placeholder="1.00" onChange={(event) => setVersion(event.target.value)} />}</FieldRow>
          <FieldRow id="guided-original" label="Original game" help="For an already translated game, choose a matching prepared original.">{(props) => <div className="actions"><input {...props} value={original} onChange={(event) => setOriginal(event.target.value)} /><Button onClick={() => action.run(async () => { const folder = await window.dazedtl.chooseFolder(); if (folder) setOriginal(folder); })}>Browse</Button></div>}</FieldRow>
          <label className="toggle"><input type="checkbox" checked={untranslated} onChange={(event) => setUntranslated(event.target.checked)} />This game is untranslated; use it as the original baseline.</label>
        </fieldset>
        {task("git_setup", "Review Git setup", { version, original, untranslated }, !preserved || !version.trim() || (!original && !untranslated))}
        <p className="muted">Review the runtime file list before creating the baseline. Local work and backups stay outside the branches.</p>
      </Section>
      <Section title="Choose files for the first pass">{filePicker}</Section>
      {backups && <details><summary>Backups and recovery</summary>{backups}</details>}
    </>}

    {step === "context" && <>
      <Section title="Prepare translation guidance">
        <p className="muted">Collect speaker names, then use the setup task to prepare this game's glossary and instructions. Review and save the documents before translating.</p>
        {!state.importedFiles.length && <p className="banner">Import your selected files in Prepare first.</p>}
        <div className="actions">
          {task("start", "Collect speaker names", { mode: "speakers" }, !baseline || !state.importedFiles.length || !state.provider.ready || !state.provider.enabled)}
          <Button disabled={disabled} onClick={() => copySkill("setup")}><Clipboard size={15} />Copy setup task</Button>
        </div>
        <details><summary>Speaker detection options</summary><EngineOptions state={state} values={values.engine_options} keys={speakers} disabled={disabled}
          change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} /></details>
      </Section>
      <ContextEditor projectId={project.id} documents={state.documents} recovered={state.drafts} disabled={disabled} />
    </>}

    {step === "translate" && <>
      {direct && <p className="muted">Translate a selection using this game's saved context and workflow. <Button variant="quiet" onClick={openGuide}>Open full guide</Button></p>}
      {!baseline && <p className="banner">Complete the original backup and Git setup in Prepare before starting a run.</p>}
      <Section title="Files to translate" hint={state.engine === "ACE" ? "Converted Ace JSON" : "Supported RPG Maker JSON"}>{filePicker}</Section>
      <Section title="Translation phase">
        <FieldRow id="guided-phase" label="Phase">{(props) => <select {...props} disabled={disabled} value={state.phase === "speakers" ? "database" : state.phase}
          onChange={(event) => action.run(async () => { await save(); await api.phase(project.id, event.target.value as Phase); })}>
          {phases.map(([id, label]) => <option value={id} key={id}>{label}</option>)}
        </select>}</FieldRow>
        <p className="muted">Translate database names first, then dialogue. Completed results and the glossary carry forward into the next phase.</p>
        <details><summary>{state.phaseFiles.length} imported files in this phase</summary><ul>{state.phaseFiles.map((name) => <li key={name}>{name}</li>)}</ul></details>
        {state.phase === "dialogue" && <label className="toggle"><input type="checkbox" checked={values.phase1_comments} disabled={disabled}
          onChange={(event) => edit("phase1_comments", event.target.checked)} />Translate supported comment continuations (408), when displayed by this game.</label>}
        {(state.phase === "advanced" || state.phase === "variables") && <>
          <p className="muted">Run the variable cache before advanced text. Enable only player-visible script, variable, and plugin text confirmed by the audit.</p>
          <Button disabled={disabled} onClick={() => copySkill("advanced")}>Copy advanced-text audit</Button>
          <EngineOptions state={state} values={values.engine_options} keys={advanced} disabled={disabled}
            change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} />
        </>}
        <details><summary>Translation options</summary><EngineOptions state={state} values={values.engine_options}
          keys={["IGNORETLTEXT", "PRESERVEORIGINAL", "FIXTEXTWRAP", "BRFLAG", "TLSYSTEMVARIABLES", "TLSYSTEMSWITCHES"]}
          disabled={disabled} change={(key, value) => edit("engine_options", { ...values.engine_options, [key]: value })} /></details>
      </Section>
      <Section title="Run translation">
        <FieldRow id="guided-mode" label="API mode">{(props) => <select {...props} disabled={disabled} value={values.mode}
          onChange={(event) => edit("mode", event.target.value as GuidedOptions["mode"])}>
          <option value="batch">Batch (recommended)</option><option value="translate">Live API</option>
        </select>}</FieldRow>
        <p className="muted">{state.provider.model || "No model selected"}{values.mode === "batch" ? " · Review the collected Batch estimate before submission." : " · Requests run as the engine processes the selected files."}</p>
        {values.mode === "batch" && !state.provider.batchSupported && <p className="muted">This connection does not support Batch. Choose a Batch-capable provider or select Live API.</p>}
        <div className="actions">
          <Button onClick={settings}>Connection and model</Button>
          {task("start", "Estimate cost", { mode: "estimate" }, !baseline || !state.phaseFiles.length || !state.provider.model)}
          <Button variant="primary" disabled={disabled || !baseline || !state.phaseFiles.length || !state.provider.ready || !state.provider.enabled || (values.mode === "batch" && !state.provider.batchSupported)}
            onClick={() => review("start", { mode: values.mode })}>{values.mode === "batch" ? "Prepare Batch translation" : "Review Live API run"}</Button>
        </div>
      </Section>
    </>}

    {step === "apply" && <>
      <Section title="Apply reviewed translations">
        <p className="muted">The project's completed phases accumulate in its translated files. Review the list, then apply the imported selection to the game.</p>
        <div className="actions">
          {task("export_selected", "Review files to apply", {}, !baseline)}
          <Button disabled={disabled} onClick={() => copySkill("plugins")}>Copy {state.engine === "ACE" ? "Ruby/script" : "plugin-text"} review task</Button>
        </div>
        {state.engine === "ACE" && <>
          <p className="muted">After applying JSON, rebuild Ace's native data before playtesting. Pack again after layout or QA changes to JSON.</p>
          {task("ace_pack", "Pack JSON into native Ace data", {}, !baseline || !state.aceAvailable)}
        </>}
      </Section>
    </>}

    {step === "layout" && <Section title="Fit translated text">
      <p className="muted">Apply translations first. Set the game's measured character widths, then preview rewrap for the imported files. Protected control codes and source fields stay intact.</p>
      <fieldset disabled={disabled}>
        {([['width', 'Dialogue'], ['faceWidth', 'Face dialogue'], ['listWidth', 'List / help'], ['noteWidth', 'Notes']] as const).map(([key, label]) =>
          <FieldRow key={key} id={"guided-width-" + key} label={label}>{(props) => <input {...props} type="number" min={20} max={300} value={values.widths[key]}
            onChange={(event) => edit("widths", { ...values.widths, [key]: Number(event.target.value) })} />}</FieldRow>)}
        <label className="toggle"><input type="checkbox" checked={onlyOverflow} onChange={(event) => setOnlyOverflow(event.target.checked)} />Only rewrap text over its width limit</label>
      </fieldset>
      <div className="actions">
        <Button disabled={disabled} onClick={() => copySkill("wrap")}>Copy width-measurement task</Button>
        {task("rewrap_preview", "Preview rewrap", layoutOptions, !baseline || !state.importedFiles.length)}
        {task("rewrap_apply", "Review and apply rewrap", layoutOptions, !baseline || !state.importedFiles.length)}
      </div>
    </Section>}

    {step === "review" && <>
      <Section title="Review and playtest">
        <p className="muted">Check translation coverage, remaining plugin or script text, images with text, and the game at runtime. The QA helper is a separate task; inspect its findings before accepting corrections.</p>
        <div className="actions">
          {task("qa_prepare", "Prepare / resume text QA", { focus: "release" }, !baseline)}
          {task("qa_status", "Refresh text QA", { focus: "release" }, !baseline)}
          {state.engine === "MVMZ" && task("playtest_install", "Install playtest tools", {}, !baseline)}
          <Button disabled={disabled} onClick={() => copySkill("walkthrough")}>Copy playtest task</Button>
        </div>
        <p className="muted">Image editing remains a separate task. Finish or deliberately exclude image text from your reviewed scope before recording readiness.</p>
        <fieldset disabled={disabled}>
          <label className="toggle"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />I reviewed the translation and resolved or documented exclusions, including image text.</label>
          <label className="toggle"><input type="checkbox" checked={playtested} onChange={(event) => setPlaytested(event.target.checked)} />I playtested this scope and checked text layout.{state.engine === "ACE" ? " The latest JSON is packed into native data." : ""}</label>
        </fieldset>
        {task("guided_review", "Record review of current files", { reviewed, playtested }, !baseline || !reviewed || !playtested)}
      </Section>
      <Section title="Build the local patch">
        <p className="muted">Save the reviewed runtime files in Git, then build a patch ZIP. Changes after your review require another review. Publishing is a separate action.</p>
        <div className="actions">
          {task("checkpoint", "Review Git checkpoint", {}, !baseline)}
          {task("guided_package", "Build local patch ZIP", {}, !baseline || !translation.lifecycle.guided_review || !translation.lifecycle.checkpoint)}
        </div>
        {translation.lifecycle.delivery && <p className="path">{translation.lifecycle.delivery.path}</p>}
      </Section>
    </>}

    {sharedJob && <Section title="Project operation">
      <JobStatus job={sharedJob} />
      {sharedJob.status === "running" && <Button disabled={action.busy} onClick={() => action.run(() => api.translation.stop(project.id, sharedJob.id))}>Stop operation</Button>}
      {sharedJob.status === "complete" && typeof sharedJob.result?.path === "string" && <p className="path">{sharedJob.result.path}</p>}
    </Section>}
    {latest && <Section title="Tool activity">
      <JobStatus job={{ label: latest.label || "Guided action", status: latest.status, message: latest.message }} />
      {latest.status === "running" && <Button disabled={action.busy} onClick={() => action.run(() => api.stop(project.id))}>Stop tool</Button>}
      {typeof latest.result?.handoff === "string" && <Button onClick={() => action.run(() => window.dazedtl.copyText(String(latest.result!.handoff)))}>Copy prepared QA task</Button>}
      {latest.result && <details><summary>Results</summary><pre>{JSON.stringify(latest.result, null, 2)}</pre></details>}
      {!!latest.log.length && <details><summary>Activity log</summary><pre>{latest.log.join("\n")}</pre></details>}
    </Section>}
    {job && <RunPanel job={job} active={running && ["running", "waiting"].includes(job.status)} busy={action.busy}
      stop={() => action.run(() => api.stop(project.id))} resume={() => setResume(true)} answer={(approved) => action.run(() => api.answer(project.id, job.approval!.token, approved))}
      exportFiles={() => action.run(async () => setOutput((await api.export(project.id)).path))} apply={() => review("export_selected")} />}
    {output && <p className="path">Output copy: {output} <Button onClick={() => action.run(() => window.dazedtl.openFolder("output", output))}>Open folder</Button></p>}
    {!direct && <footer className="guided-footer">
      <Button disabled={action.busy || stepIndex === 0} onClick={() => move(steps[stepIndex - 1].id)}><ArrowLeft size={15} />Back</Button>
      <span className="muted">Step {stepIndex + 1} of {steps.length}</span>
      <Button disabled={action.busy || stepIndex === steps.length - 1} onClick={() => move(steps[stepIndex + 1].id)}>Continue<ArrowRight size={15} /></Button>
    </footer>}
    {preview && <Modal label="Review guided action" dismissible={!action.busy} onDismiss={() => setPreview(null)}>
      <h2>{preview.label}</h2><p className="path">{preview.destination}</p>
      {!!preview.paths.length && <><p>{preview.paths.length} files in this action</p><ul>{preview.paths.map((name) => <li key={name}>{name}</li>)}</ul></>}
      {!!preview.additions?.length && <details><summary>{preview.additions.length} files absent from the original baseline</summary><ul>{preview.additions.map((name) => <li key={name}>{name}</li>)}</ul></details>}
      {preview.action === "git_setup" && <p>Version {String(preview.options.version)} · {preview.options.untranslated ? "Use the selected untranslated game as the original." : "Original: " + String(preview.options.original)}</p>}
      {preview.action === "import" && <p>This replaces the project's imported selection. Completed translations and saved runs are retained.</p>}
      {preview.action === "export_selected" && <p>This replaces the selected game data with the accumulated translated files.</p>}
      {paid && <p>{state.provider.model} · {preview.options.mode === "batch" ? "The engine collects the batch for a separate cost review before submission. Speaker preparation may request approval." : "API requests may incur charges using this run's saved settings."}</p>}
      {preview.action === "guided_review" && <p>This records your review and playtest for the exact current files.</p>}
      {preview.rewrap && <>
        <p>{preview.rewrap.changes_found} changes · {preview.rewrap.overflow_skipped} protected overflows skipped</p>
        {preview.rewrap.previews.map((row, index) => <details key={index}><summary>{row.file_name} · {row.locator}</summary>
          <strong>Before</strong><pre>{row.before}</pre><strong>After</strong><pre>{row.after}</pre>
        </details>)}
      </>}
      <Message message={action.error} />
      <div className="actions"><Button disabled={action.busy} onClick={() => setPreview(null)}>Cancel</Button><Button variant="primary" disabled={action.busy} onClick={() => action.run(async () => {
        await api.execute(project.id, preview.token); setPreview(null);
      })}>{paid && preview.options.mode === "translate" ? "Approve and start Live API" : "Run this action"}</Button></div>
    </Modal>}
    {resume && <Modal label="Resume saved run" dismissible={!action.busy} onDismiss={() => setResume(false)}>
      <h2>Resume saved run?</h2><p>Continue with its frozen files, context and provider settings. Remaining API requests may incur charges.</p><Message message={action.error} />
      <div className="actions"><Button disabled={action.busy} onClick={() => setResume(false)}>Cancel</Button><Button variant="primary" disabled={action.busy} onClick={() => action.run(async () => { await api.resume(project.id); setResume(false); })}>Resume</Button></div>
    </Modal>}
  </PageLayout>;
}
