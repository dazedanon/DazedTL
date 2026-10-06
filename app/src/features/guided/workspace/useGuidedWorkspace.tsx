import { useEffect, useEffectEvent, useRef, useState } from "react";
import { api } from "../../../api/client";
import type {
  GuidedForm,
  GuidedOptions,
  GuidedState,
  GuidedStep,
  Job,
  Phase,
  Preview,
  TranslationState,
} from "../../../api/contracts";
import { useApplication } from "../../../app/ApplicationProvider";
import { flushDrafts } from "../../../state/leaveGuards";
import { useAction } from "../../../state/useAction";
import { useDraft } from "../../../state/useDraft";
import { useOnChange } from "../../../state/useOnChange";
import { ActionControl } from "../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../ui/ActionList";
import { Button } from "../../../ui/Button";
import { projectActivity } from "../ActivityHistory";
import type { SourceReview } from "../EventTextReview";
import type { ImageEntryMode } from "../GuidedImages";
import type { RequestInspectionTarget } from "../ProcessPanel";
import { investigationResults } from "../contextView";
import {
  type SelectorKey,
  type SourcePickerDraft,
  sourceErrors,
} from "../eventTextSelection";
import {
  guidanceAvailability,
  guidanceNames,
  saveGuidanceSet,
} from "../guidanceReview";
import {
  completeForSelection,
  observedRun,
  selectionSettled,
  translationTaskComplete,
} from "../translationView";
import { useContextDraft } from "../useContextDraft";
import { useGuidedWorkflow } from "../useGuidedWorkflow";
import { useTranslationFlow } from "../useTranslationFlow";
import { initialPosition, stagesFor } from "../workflow";
import {
  type GuidedProps,
  type Panel,
  actionKey,
  advanced,
  advancedCodes,
  fileCount,
  jobTime,
} from "./model";

/** Shared state, derived values and actions behind every Guided task view. */
export function useGuidedWorkspace({
  project,
  state,
  translation,
  settings,
  backups,
  versions,
}: GuidedProps & { state: GuidedState; translation: TranslationState }) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const speakerAction = useAction({ after: application.settle });
  const draft = useGuidedWorkflow(state, action.report);
  const context = useContextDraft(project.id, state.drafts, action.report);
  const form = useDraft("guided-form:" + project.id, {
    initial: { saved: state.form },
    report: action.report,
    persist: (value) => api.guided.form(project.id, value),
  });
  const values = draft.value.values,
    fields = form.value || state.form;
  // An action error describes the inputs it ran with; editing them retires it.
  const retireError = () => {
    if (action.error) action.clear();
  };
  useOnChange(draft.value, retireError);
  useOnChange(form.value, retireError);
  const stages = stagesFor(state.engine);
  const position = initialPosition(state, translation);
  const stage = stages.find((item) => item.id === position.step)!;
  const selectedTask = stage.tasks.find((item) => item.id === position.task);
  const taskId = selectedTask?.id || "run";
  const taskView =
    taskId === "other-event-text"
      ? state.eventText.view
      : taskId === "apply"
        ? state.form.text.view
        : taskId;
  const taskIndex = stage.tasks.findIndex((item) => item.id === taskId);
  const showTaskTabs = stage.tasks.length > 1;
  const taskTabsId = `${stage.id}-tasks`;
  const [panel, setPanel] = useState<Panel>(null);
  const [speakerTab, setSpeakerTab] = useState("findings");
  const [imageView, setImageView] = useState<ImageEntryMode | null>(null);
  const [editorAssets, setEditorAssets] = useState<string[] | null>(null);
  const [utilityActions, setUtilityActions] = useState<HTMLDivElement | null>(
    null,
  );
  const [pluginFooter, setPluginFooter] = useState<HTMLDivElement | null>(null);
  const [fileBaseline, setFileBaseline] = useState<string[]>([]);
  const [fileScope, setFileScope] = useState<"database" | "dialogue" | null>(
    null,
  );
  const [preview, setPreview] = useState<Preview | null>(null);
  const [attemptedPreview, setAttemptedPreview] = useState("");
  const [previewRequest, setPreviewRequest] = useState<{
    name: string;
    options: Record<string, unknown>;
    files?: string[];
  } | null>(null);
  const [inspectRelease, setInspectRelease] = useState(false);
  const [submission, setSubmission] = useState<Job | null>(null);
  const seenApprovals = useRef(new Set<string>());
  const [resume, setResume] = useState<Job | null>(null);
  const [sourceReview, setSourceReview] = useState<SourceReview | null>(null);
  const [comparisonReview, setComparisonReview] = useState(false);
  const [comparisonsAccepted, setComparisonsAccepted] = useState(false);
  const [history, setHistory] = useState<string | null>(null);
  const [inspection, setInspected] = useState<Job | null>(null);
  const [inspectionTarget, setInspectionTarget] =
    useState<RequestInspectionTarget>();
  const inspected = observedRun(
    inspection,
    state.runs.find((run) => run.id === inspection?.id),
  );
  const [started, setStarted] = useState<Record<string, Job>>({});

  const documentName = state.contextDocument;
  const setDocumentName = (name: string) => {
    void action.run(async () =>
      application.navigateGuided(project.id, { contextDocument: name }),
    );
  };
  const [baselineRun, setBaselineRun] = useState<string | null>(null);
  const [baselineNotice, setBaselineNotice] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const historyControl = useRef<HTMLButtonElement>(null);
  const [inspectorReturnFocus, setInspectorReturnFocus] =
    useState<HTMLElement | null>(null);
  useEffect(() => {
    bodyRef.current?.scrollTo(0, 0);
    headingRef.current?.focus({ preventScroll: true });
  }, [taskId, taskView, position.step]);
  const running = !!application.snapshot?.application.running;
  const operationBusy =
    action.busy || speakerAction.busy || draft.committing || context.committing;
  const sourceBackup = translation.lifecycle.source_backup;
  const preserved = !!sourceBackup && sourceBackup.available !== false;
  const baseline = preserved && !!translation.git?.configured;
  const job = state.run;
  const findings = state.speakerSetup;
  const scan = state.speakerScan;
  const discovery = state.contextSetup;
  const guidance = guidanceAvailability(discovery.documents);
  const investigation = investigationResults(state);
  const scanOptionsDirty =
    JSON.stringify(values.engine_options) !==
      JSON.stringify(state.preferences.values.engine_options) ||
    values.phase1_comments !== state.preferences.values.phase1_comments;
  const widthsDirty =
    JSON.stringify(values.widths) !==
    JSON.stringify(state.preferences.values.widths);
  const changed = state.sourceStatus.changed;
  const selectedFiles = new Set(values.selected);
  const eventFiles = state.files.filter(
    (file) => file.group === "dialogue" && selectedFiles.has(file.name),
  );
  const databaseFiles = state.files.filter(
    (file) => file.group === "database" && selectedFiles.has(file.name),
  );
  const outputFiles = state.readiness.outputs.filter((name) =>
    selectedFiles.has(name),
  );
  const applied =
    outputFiles.length > 0 &&
    outputFiles.every((name) => state.readiness.applied.includes(name));
  const layoutFiles = state.files
    .filter((file) => selectedFiles.has(file.name))
    .map((file) => file.name);
  const enabledCodes = advancedCodes.filter(
    (key) => values.engine_options[key] === true,
  );
  const sourceChoicesSaved = [...advanced, "AUTONAMEPOPUP101"].every(
    (key) =>
      JSON.stringify(values.engine_options[key]) ===
      JSON.stringify(state.preferences.values.engine_options[key]),
  );
  const advancedReady =
    enabledCodes.length > 0 &&
    !sourceErrors(state.eventText, values.engine_options).length &&
    state.eventText.accepted &&
    sourceChoicesSaved;
  const mode = values.mode;
  const paidModeReady = mode !== "batch" || state.provider.batchSupported;
  const pickerFiles = state.files.filter(
    (file) => !fileScope || file.group === fileScope,
  );
  const pickerSelected = values.selected.filter((name) =>
    pickerFiles.some((file) => file.name === name),
  );
  const phase: Phase =
    taskView === "advanced-run"
      ? "advanced"
      : taskView === "dialogue"
        ? "dialogue"
        : taskView === "variables"
          ? "variables"
          : "database";
  const phaseFiles = phase === "database" ? databaseFiles : eventFiles;
  const currentEstimate = (target: Phase) =>
    !changed.length &&
    !draft.dirty &&
    !Object.keys(context.drafts).length &&
    state.estimates[target]?.current
      ? state.estimates[target]?.job
      : null;
  const activity = projectActivity(state.operations, translation.jobs);
  const activeOperation = activity.find((item) =>
    ["ready", "running", "waiting"].includes(item.status),
  );
  const localOperation =
    !panel &&
    activeOperation &&
    ((taskId === "backup" && activeOperation.action === "backup_source") ||
      (taskId === "format" &&
        [
          "prepare_game",
          "format_data",
          "format_plugins",
          "gameupdate",
        ].includes(activeOperation.action || "")))
      ? activeOperation
      : null;
  const backupPending =
    taskId === "backup" &&
    (!!localOperation || (action.busy && action.key === "backup_source"));
  const preparationPending =
    taskId === "format" &&
    (!!localOperation || (action.busy && action.key === "prepare_game"));
  const stopOperation = (current: Job) =>
    action.run(
      async () => {
        if (state.operations.some((item) => item.id === current.id))
          await api.stop(project.id);
        else await api.translation.stop(project.id, current.id);
      },
      "",
      "stop-operation",
    );
  const qaTask = state.readiness.qa.current
    ? activity.find(
        (item) =>
          item.action === "qa_prepare" &&
          item.result?.task === state.readiness.qa.task &&
          typeof item.result?.handoff === "string",
      )
    : undefined;
  const qaJob = activity.find(
    (item) =>
      ["qa_prepare", "qa_status"].includes(item.action || "") &&
      item.status === "complete",
  );
  const qa = state.readiness.qa;
  const chosenFindings =
    fields.text.findings_task === qa.task ? fields.text.findings : [];
  const qaStatus = qa.status;
  const release = fields.release;
  const releaseAction = release.kind === "game" ? "release" : "release_patch";
  const releasePath =
    release.directory.replace(/[\\/]+$/, "") + "/" + release.name;
  const artifact = state.artifacts.find((item) => item.kind === release.kind);

  const edit = <K extends keyof GuidedOptions>(
    key: K,
    value: GuidedOptions[K],
  ) =>
    draft.session.edit((current) => ({
      ...current,
      values: { ...current.values, [key]: value },
    }));
  const editForm = <K extends keyof GuidedForm>(key: K, value: GuidedForm[K]) =>
    form.session.edit((current) => ({ ...current, [key]: value }));
  const editRelease = <K extends keyof GuidedForm["release"]>(
    key: K,
    value: GuidedForm["release"][K],
  ) =>
    form.session.edit((current) => ({
      ...current,
      release: { ...current.release, [key]: value },
    }));
  const editText = <K extends keyof GuidedForm["text"]>(
    key: K,
    value: GuidedForm["text"][K],
  ) =>
    form.session.edit((current) => ({
      ...current,
      text: { ...current.text, [key]: value },
    }));
  const save = async () => {
    await flushDrafts();
    if (draft.session.getSnapshot().dirty || state.optionsDraft)
      await draft.save();
  };
  const translationFlow = useTranslationFlow({
    projectId: project.id,
    phase,
    mode,
    files: phaseFiles.map((file) => file.name),
    state,
    dirty: draft.dirty || !!Object.keys(context.drafts).length,
    busy: operationBusy,
    save,
    settle: application.settle,
  });
  const disabled = operationBusy || translationFlow.active;

  const navigate = async (step: GuidedStep, task: string) => {
    await flushDrafts();
    application.navigateGuided(project.id, { step, task });
  };
  const move = (step: GuidedStep, task: string) =>
    action.run(
      async () => {
        await navigate(step, task);
        setPanel(null);
      },
      "",
      "position",
    );
  const eventStep = (view: GuidedState["eventText"]["view"]) =>
    action.run(
      async () => {
        await flushDrafts();
        application.navigateGuided(project.id, {
          step: "translate",
          task: "other-event-text",
          eventView: view,
        });
        setPanel(null);
      },
      "",
      "event-text:step",
    );
  const stepTask = (task: string) => {
    if (["audit", "sources", "advanced-run", "variables"].includes(task)) {
      void eventStep(task as GuidedState["eventText"]["view"]);
      return;
    }
    const owner = stages.find((item) =>
      item.tasks.some((entry) => entry.id === task),
    );
    if (owner) void move(owner.id, task);
  };
  const openSourcePicker = (key: SelectorKey) =>
    action.run(
      async () => {
        await flushDrafts();
        const selected = Array.isArray(values.engine_options[key])
          ? [...values.engine_options[key]]
          : [];
        await api.guided.eventTextPicker(project.id, {
          key,
          selected,
          baseline: [...selected],
          query: "",
          filter: "all",
        });
      },
      "",
      "event-text:picker",
    );
  const saveSourcePicker = async (selection: SourcePickerDraft) => {
    const current = draft.session.getSnapshot().value!;
    if (
      JSON.stringify(current.values.engine_options[selection.key]) !==
      JSON.stringify(selection.baseline)
    )
      throw new Error(
        "These source choices changed elsewhere. Cancel and reopen the picker.",
      );
    draft.session.edit((value) => ({
      ...value,
      values: {
        ...value.values,
        engine_options: {
          ...value.values.engine_options,
          [selection.key]: selection.selected,
        },
      },
    }));
    await draft.save();
    await api.guided.eventTextPicker(project.id, null);
  };
  const reviewSources = () =>
    action.run(
      async () => {
        await save();
        const current = await api.guided.eventTextRequest(project.id);
        const saved = draft.session.getSnapshot().value!;
        setSourceReview({
          state: current.findings,
          revision: saved.revision,
          values: saved.values.engine_options,
        });
      },
      "",
      "event-text:review",
    );
  const skipEventText = () =>
    stepTask(
      state.comparisons.status !== "not_needed" ? "variables" : "plugins",
    );
  const next = () => {
    if (taskIndex < 0) return stage.tasks[0];
    return (
      stage.tasks[taskIndex + 1] || stages[stages.indexOf(stage) + 1]?.tasks[0]
    );
  };
  const previous = () =>
    taskIndex > 0
      ? stage.tasks[taskIndex - 1]
      : stages[stages.indexOf(stage) - 1]?.tasks.at(-1);
  /** Every task's footer starts with the same way back. */
  const back = () => {
    const target = previous();
    return (
      target && (
        <Button
          variant="quiet"
          disabled={action.busy}
          onClick={() => stepTask(target.id)}
        >
          Back
        </Button>
      )
    );
  };
  const advance = (
    label?: string,
    target = next(),
    variant: "primary" | "quiet" = "primary",
  ) =>
    target && (
      <Button
        variant={variant}
        disabled={action.busy || draft.committing || context.committing}
        onClick={() => stepTask(target.id)}
      >
        {label ||
          "Continue to " +
            (stage.tasks.includes(target)
              ? target.title.toLowerCase()
              : stages.find((item) => item.tasks.includes(target))!.short)}
      </Button>
    );
  // Controls report their own action; fallback messages skip owned keys.
  const feedback = (key: string, pendingText = "Working…") => ({
    feedbackKey: key,
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  const operationJob = (
    name: string,
    options: Record<string, unknown> = {},
  ): Job | undefined => {
    const recorded: Job[] =
      name === "start"
        ? state.run && state.run.mode === options.mode
          ? [state.run]
          : []
        : [
            ...state.operations.filter(
              (item) =>
                item.action === name &&
                (name !== "runtime_restore" ||
                  item.result?.restored === options.publication),
            ),
            ...translation.jobs
              .filter(
                (item) => item.kind === "operation" && item.action === name,
              )
              .map((item) => ({
                id: item.id,
                action: item.action || undefined,
                label: item.label,
                status: item.status,
                message: item.message,
                created: item.created,
                updated: item.updated,
                result: item.result,
                log: [],
              })),
          ];
    const acknowledged = started[actionKey(name, options)];
    if (acknowledged && !recorded.some((item) => item.id === acknowledged.id))
      recorded.push(acknowledged);
    return recorded.sort((a, b) => jobTime(b) - jobTime(a))[0];
  };
  const execute = async (value: Preview) => {
    setAttemptedPreview(value.token);
    const result = await api.execute(project.id, value.token);
    setStarted((previous) => ({
      ...previous,
      [actionKey(value.action, value.options)]: result,
    }));
    setPreview(null);
    if (value.action === "git_setup") setBaselineRun(result.id);
    if (value.action === "start") {
      if (value.options.mode !== "estimate")
        await navigate(
          value.options.mode === "speakers" ? "context" : "translate",
          value.options.mode === "speakers"
            ? "run"
            : phase === "advanced" || phase === "variables"
              ? "other-event-text"
              : phase,
        );
    }
  };
  const preparePreview = async (
    name: string,
    options: Record<string, unknown>,
    files?: string[],
  ) => {
    await save();
    const { phase, ...requestOptions } = options;
    if (name === "start" && phase) await api.phase(project.id, phase as Phase);
    return api.preview(project.id, name, files, requestOptions);
  };
  const review = (
    name: string,
    options: Record<string, unknown> = {},
    files?: string[],
    inspectOnly = false,
  ) =>
    action.run(
      async () => {
        setInspectRelease(
          inspectOnly && ["release", "release_patch"].includes(name),
        );
        const result = await preparePreview(name, options, files);
        setPreviewRequest({
          name,
          options: { ...options },
          files: files && [...files],
        });
        const prepareBatch = name === "start" && options.mode === "batch";
        if ((!result.confirmation || prepareBatch) && !inspectOnly)
          await execute(result);
        else setPreview(result);
      },
      "",
      actionKey(name, options),
    );
  const refreshPreview = () =>
    action.run(
      async () => {
        const request = previewRequest;
        if (request)
          setPreview(
            await preparePreview(request.name, request.options, request.files),
          );
      },
      "",
      "review:refresh",
    );
  const previewUsed = preview?.token === attemptedPreview;
  const cancelPreview = () =>
    action.run(
      async () => {
        const estimate = preview?.estimate?.jobId;
        if (
          estimate &&
          state.runs.some((run) => run.id === estimate && run.temporary)
        )
          await api.guided.discardPreparation(project.id, estimate);
        setPreview(null);
      },
      "",
      "review:cancel",
    );
  const translateSelected = () => translationFlow.start();
  useEffect(() => {
    if (
      action.busy ||
      translationFlow.active ||
      panel ||
      inspection ||
      inspectionTarget ||
      history ||
      preview ||
      submission ||
      position.step !== "translate"
    )
      return;
    const pending = state.runs.find(
      (run) =>
        run.approval &&
        !translationFlow.claimed.has(run.id) &&
        !seenApprovals.current.has(run.approval.token),
    );
    if (pending?.approval) {
      seenApprovals.current.add(pending.approval.token);
      setSubmission(pending);
    }
  }, [
    state.runs,
    action.busy,
    translationFlow.active,
    panel,
    inspection,
    inspectionTarget,
    history,
    preview,
    submission,
    position.step,
    translationFlow.claimed,
  ]);
  const task = (
    name: string,
    label: string,
    options: Record<string, unknown> = {},
    /** True, or the reason shown beside the disabled control. */
    blocked: boolean | string = false,
    variant: "default" | "primary" = "default",
    files?: string[],
  ) => {
    const blockedReason = typeof blocked === "string" ? blocked : "";
    const recorded =
      name === "start"
        ? options.mode === "estimate"
          ? state.estimates[options.phase as Phase]?.job || undefined
          : undefined
        : operationJob(name, options);
    const current =
      name === "backup_source" && recorded?.status === "complete"
        ? undefined
        : recorded;
    const active =
      current && ["ready", "running", "waiting"].includes(current.status);
    const publicationReview = [
      "export_selected",
      "rewrap_apply",
      "qa_apply",
    ].includes(name);
    const appliedHere =
      name === "export_selected" &&
      current?.status === "complete" &&
      current.id === started[actionKey(name, options)]?.id;
    const qaOperation = ["qa_prepare", "qa_status"].includes(name);
    const display =
      current?.status === "complete" &&
      (publicationReview ||
        (qaOperation && (!qa.current || current.result?.task !== qa.task)))
        ? undefined
        : current;
    const localFeedback =
      !panel &&
      ((taskId === "backup" && name === "backup_source") ||
        (taskId === "format" && name === "prepare_game"));
    if (name === "refresh_sources")
      return (
        <ActionControl
          inline
          label={label}
          disabled={disabled || !!blocked}
          variant="quiet"
          {...feedback(name, active ? "Resyncing files…" : "Preparing resync…")}
          pending={(action.busy && action.key === name) || !!active}
          notice={
            !active &&
            current?.status === "complete" &&
            current.id === started[name]?.id
              ? `${typeof current.result?.files === "number" ? fileCount(current.result.files) : "Files"} resynced.`
              : ""
          }
          error={
            (action.key === name && action.error) ||
            (current &&
              ["failed", "interrupted"].includes(current.status) &&
              current.message) ||
            ""
          }
          onClick={() => review(name, options, files)}
        />
      );
    if (localFeedback)
      return (
        <Button
          variant={variant}
          pending={
            !!active || (action.busy && action.key === actionKey(name, options))
          }
          disabled={disabled || !!blocked}
          onClick={() => review(name, options, files)}
        >
          {label}
        </Button>
      );
    if (localOperation?.action === name)
      return (
        <Button variant={variant} pending disabled>
          {label}
        </Button>
      );
    return (
      <ActionControl
        label={label}
        disabled={disabled || !!blocked}
        disabledReason={blockedReason}
        variant={variant}
        {...feedback(
          actionKey(name, options),
          active
            ? current.message || "Working…"
            : name === "start" && options.mode === "estimate"
              ? "Estimating selected files…"
              : "Preparing action…",
        )}
        {...(appliedHere ? { notice: "Saved translations applied." } : {})}
        pending={
          (action.busy && action.key === actionKey(name, options)) || !!active
        }
        job={
          display &&
          !active &&
          !(options.mode === "estimate" && display.status === "complete")
            ? display
            : undefined
        }
        onClick={() => review(name, options, files)}
      />
    );
  };
  const workingFileActions = () => (
    <>
      <ActionRow
        label={
          <>
            <strong>Saved translations</strong>
            <small>
              Open the persistent translated folder to inspect or copy its JSON
              files. Some files may contain partial progress.
            </small>
          </>
        }
      >
        <ActionControl
          label="Open translated folder"
          disabled={disabled}
          {...feedback("translated-folder", "Opening folder…")}
          onClick={() =>
            action.run(
              async () => {
                const folder = await api.guided.outputFolder(project.id);
                await window.dazedtl.openFolder("output", folder.path);
              },
              "Translated folder opened.",
              "translated-folder",
            )
          }
        />
      </ActionRow>
    </>
  );
  const resyncPending = ["ready", "running", "waiting"].includes(
    operationJob("refresh_sources")?.status || "",
  );
  const copyTask = (
    name: string,
    label: string,
    variant: "default" | "primary" | "quiet" | "link" = "default",
  ) => (
    <ActionControl
      label={label}
      variant={variant}
      disabled={disabled}
      {...feedback("copy:" + name, "Copying…")}
      onClick={() =>
        action.run(
          async () => {
            await save();
            await window.dazedtl.copyText(
              (await api.guided.skill(project.id, name)).text,
            );
          },
          name === "setup"
            ? "Investigation task copied. Paste it into your assistant."
            : "Task copied. Return to its saved results when your assistant finishes.",
          "copy:" + name,
        )
      }
    />
  );
  const inspect = (item: Job | null, target?: RequestInspectionTarget) => {
    const current = document.activeElement;
    setInspectorReturnFocus(
      current instanceof HTMLElement ? current : historyControl.current,
    );
    setInspectionTarget(target);
    setInspected(item);
  };
  const chooseFiles = (scope: "database" | "dialogue" | null = null) => {
    setFileScope(scope);
    setFileBaseline([...values.selected]);
    setPanel("files");
  };
  const closePanel = () =>
    panel === "files"
      ? action.run(
          async () => {
            edit("selected", fileBaseline);
            await flushDrafts();
            setPanel(null);
          },
          "",
          "files:cancel",
        )
      : setPanel(null);
  const chooseFolder = (key: "original" | "release") =>
    action.run(
      async () => {
        const folder = await window.dazedtl.chooseFolder();
        if (!folder) return;
        if (key === "original") editForm("original", folder);
        else editRelease("directory", folder);
      },
      "",
      "folder:" + key,
    );
  const savedNames = guidanceNames(state.documents, context.drafts);
  const saveDocuments = (names: string[]) =>
    action.run(
      async () => {
        for (const name of names) {
          if (!discovery.documents[name]?.exists && !context.drafts[name])
            context.edit(
              name,
              state.documents[name]?.text || "",
              state.documents[name]?.revision || "",
            );
        }
        await saveGuidanceSet(names, context.save);
      },
      "Guidance saved.",
      "context:save",
    );
  const layoutOptions = {
    files: layoutFiles,
    widths: values.widths,
    categories: fields.text.categories,
    codes: fields.text.codes,
    max_rows: fields.text.max_rows,
    protect_rows: fields.text.protect_rows,
    over_limit: fields.only_overflow,
  };
  const fitting = activity.find(
    (item) => item.id === state.readiness.layout_scan,
  )?.result as Preview["rewrap"] | undefined;
  const fittingSettingsSaved =
    fields.only_overflow === state.form.only_overflow &&
    ["categories", "codes", "max_rows", "protect_rows"].every(
      (key) =>
        JSON.stringify(fields.text[key as keyof GuidedForm["text"]]) ===
        JSON.stringify(state.form.text[key as keyof GuidedForm["text"]]),
    );
  const textView = (view: GuidedForm["text"]["view"]) =>
    action.run(
      async () => {
        await flushDrafts();
        application.navigateGuided(project.id, { textView: view });
      },
      "",
      "text:view",
    );
  const releaseButton = (
    <Button
      variant="quiet"
      disabled={action.busy || form.committing}
      onClick={() => stepTask("package")}
    >
      Continue to Release
    </Button>
  );
  const widths = (
    <fieldset disabled={disabled} className="guided-widths">
      {(
        [
          ["width", "Dialogue"],
          ["faceWidth", "With portrait"],
          ["listWidth", "List / help"],
          ["noteWidth", "Notes"],
        ] as const
      ).map(([key, label]) => (
        <label key={key}>
          {label}
          <input
            aria-label={label + " width in characters"}
            type="number"
            min={20}
            max={key === "faceWidth" ? values.widths.width : 300}
            value={values.widths[key]}
            onChange={(event) =>
              edit("widths", {
                ...values.widths,
                [key]: Number(event.target.value),
              })
            }
          />
        </label>
      ))}
    </fieldset>
  );
  const fileSummary = (
    count = values.selected.length,
    scope: "database" | "dialogue" | null = null,
  ) => (
    <ActionList>
      <ActionRow
        label={
          <>
            <strong>{fileCount(count)} selected</strong>
            <small>
              Selections remain checked when you filter, switch phases, or
              return later.
            </small>
          </>
        }
      >
        <Button disabled={disabled} onClick={() => chooseFiles(scope)}>
          Choose files
        </Button>
      </ActionRow>
    </ActionList>
  );
  const connection = (
    <div className="guided-connection">
      <div>
        <span>
          {state.provider.connection} ·{" "}
          {state.provider.model || "No model selected"}
        </span>
        <Button variant="quiet" onClick={settings}>
          Connection & model
        </Button>
      </div>
      <div className="guided-mode" role="group" aria-label="Translation mode">
        <Button
          aria-pressed={mode === "translate"}
          disabled={disabled}
          onClick={() => edit("mode", "translate")}
        >
          Live API
        </Button>
        {state.provider.batchSupported && (
          <Button
            aria-pressed={mode === "batch"}
            disabled={disabled}
            onClick={() => edit("mode", "batch")}
          >
            Batch API
          </Button>
        )}
      </div>
      {!state.provider.ready && (
        <p className="muted">Configure a connection before paid translation.</p>
      )}
      {!state.provider.enabled && (
        <p className="muted">
          Provider execution is disabled for this launch. Local estimates are
          available.
        </p>
      )}
    </div>
  );
  const formatActions = [
    {
      id: "format_data",
      title: "Format game data",
      hint: "Prepare the JSON used by the translation phases.",
    },
    ...(state.hasPlugins
      ? [
          {
            id: "format_plugins",
            title: "Format plugins.js",
            hint: "Prepare the game’s plugin configuration.",
          },
        ]
      : []),
    {
      id: "gameupdate",
      title: "Create GameUpdate files",
      hint: "Add player patch support.",
    },
  ];
  const preparation = state.preparation;
  const preparationComplete = preparation.complete;
  const aceNeedsExport = state.engine === "ACE" && !state.files.length;
  // A saved baseline continues to Context once. Failed attempts stay
  // on this task; a later review tracks its own run.
  const baselineSaved =
    baseline &&
    !!baselineRun &&
    translation.jobs.find((item) => item.id === baselineRun)?.status ===
      "complete";
  const continueAfterBaseline = useEffectEvent(() => {
    const version = translation.git?.original_version || "baseline";
    void move("context", "names").then(() => {
      setBaselineRun(null);
      setBaselineNotice(`Version ${version} saved. Prepare complete.`);
    });
  });
  useEffect(() => {
    if (baselineSaved && !action.busy && taskId === "baseline")
      continueAfterBaseline();
  }, [baselineSaved, action.busy, taskId]);
  const applyRun = (current: Job) => (
    <Button
      variant="primary"
      disabled={disabled || !current.outputsAvailable || !baseline}
      onClick={() =>
        review("export_selected", {}, Object.keys(current.outputs || {}))
      }
    >
      Apply translated output
    </Button>
  );
  const nextRun = (current: Job) => (
    <Button
      disabled={action.busy}
      onClick={() =>
        stepTask(
          current.logicalPhase === "database"
            ? "dialogue"
            : current.logicalPhase === "dialogue"
              ? "audit"
              : current.logicalPhase === "advanced" &&
                  state.comparisons.status !== "not_needed"
                ? "variables"
                : "plugins",
        )
      }
    >
      {current.logicalPhase === "database"
        ? "Continue to maps & events"
        : current.logicalPhase === "dialogue"
          ? "Continue to event / plugin codes"
          : current.logicalPhase === "advanced" &&
              state.comparisons.status !== "not_needed"
            ? "Review comparisons"
            : "Continue to plugin text"}
    </Button>
  );
  const phaseComplete = (target: Phase) => {
    if (target === "database" || target === "dialogue")
      return translationTaskComplete(state, target);
    const saved = state.phaseRuns[target];
    const names = eventFiles.map((file) => file.name);
    return (
      (!!saved && completeForSelection(saved, names)) ||
      selectionSettled(state, target, names)
    );
  };
  const completed = new Set<string>([
    ...(preserved ? ["backup"] : []),
    ...(baseline ? ["baseline"] : []),
    ...(applied ? ["apply"] : []),
    ...(phaseComplete("database") ? ["database"] : []),
    ...(phaseComplete("dialogue") ? ["dialogue"] : []),
    ...(phaseComplete("advanced") &&
    (state.comparisons.status === "not_needed" ||
      (state.comparisons.status === "ready" && phaseComplete("variables")))
      ? ["other-event-text"]
      : []),
    ...(investigation.every((row) => row.saved) ? ["names"] : []),
    ...(guidance.complete ? ["guidance"] : []),
    ...(discovery.layoutStatus === "saved" && !widthsDirty ? ["speakers"] : []),
    ...(preparationComplete || baseline ? ["format"] : []),
    ...(state.tools?.inspector.installed && state.tools.forge.installed
      ? ["tools"]
      : []),
  ]);
  const applySpeakerControl = findings.status === "ready" && (
    <ActionControl
      label={
        draft.dirty || state.optionsDraft
          ? "Save edits & apply findings"
          : "Apply investigated rules"
      }
      disabled={disabled}
      pending={speakerAction.busy}
      pendingText="Applying rules…"
      error={speakerAction.error}
      notice={speakerAction.notice}
      onClick={() =>
        speakerAction.run(
          async () => {
            await save();
            await draft.applySpeakers();
          },
          "Speaker rules configured.",
          "apply",
        )
      }
    />
  );
  return {
    project,
    state,
    translation,
    settings,
    backups,
    versions,
    application,
    action,
    speakerAction,
    draft,
    context,
    form,
    values,
    stages,
    position,
    stage,
    selectedTask,
    taskId,
    taskView,
    taskIndex,
    showTaskTabs,
    taskTabsId,
    panel,
    setPanel,
    speakerTab,
    setSpeakerTab,
    imageView,
    setImageView,
    editorAssets,
    setEditorAssets,
    utilityActions,
    setUtilityActions,
    pluginFooter,
    setPluginFooter,
    fileScope,
    preview,
    setPreview,
    previewRequest,
    setPreviewRequest,
    inspectRelease,
    setInspectRelease,
    submission,
    setSubmission,
    resume,
    setResume,
    sourceReview,
    setSourceReview,
    comparisonReview,
    setComparisonReview,
    comparisonsAccepted,
    setComparisonsAccepted,
    history,
    setHistory,
    setInspected,
    inspectionTarget,
    setInspectionTarget,
    inspected,
    started,
    documentName,
    setDocumentName,
    baselineNotice,
    bodyRef,
    headingRef,
    historyControl,
    inspectorReturnFocus,
    running,
    sourceBackup,
    preserved,
    baseline,
    job,
    findings,
    scan,
    discovery,
    investigation,
    scanOptionsDirty,
    widthsDirty,
    changed,
    eventFiles,
    outputFiles,
    applied,
    layoutFiles,
    enabledCodes,
    advancedReady,
    mode,
    paidModeReady,
    pickerFiles,
    pickerSelected,
    phase,
    phaseFiles,
    currentEstimate,
    activeOperation,
    localOperation,
    backupPending,
    preparationPending,
    stopOperation,
    qaTask,
    qaJob,
    qa,
    chosenFindings,
    qaStatus,
    release,
    releaseAction,
    releasePath,
    artifact,
    edit,
    editForm,
    editRelease,
    editText,
    save,
    translationFlow,
    disabled,
    navigate,
    move,
    stepTask,
    openSourcePicker,
    saveSourcePicker,
    reviewSources,
    skipEventText,
    advance,
    back,
    feedback,
    operationJob,
    execute,
    preparePreview,
    review,
    refreshPreview,
    previewUsed,
    cancelPreview,
    translateSelected,
    task,
    workingFileActions,
    resyncPending,
    copyTask,
    inspect,
    chooseFiles,
    closePanel,
    chooseFolder,
    savedNames,
    saveDocuments,
    layoutOptions,
    fitting,
    fittingSettingsSaved,
    textView,
    releaseButton,
    widths,
    fileSummary,
    connection,
    formatActions,
    preparation,
    preparationComplete,
    aceNeedsExport,
    applyRun,
    nextRun,
    completed,
    applySpeakerControl,
    fields,
  };
}

export type GuidedWorkspace = ReturnType<typeof useGuidedWorkspace>;
