import { FolderOpen } from "lucide-react";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import { api } from "../../../api/client";
import type {
  AssistantTaskKind,
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
import { useRead } from "../../../state/useRead";
import { shortcutKeys, shortcutLabel } from "../../../state/useShortcut";
import { ActionControl } from "../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../ui/ActionList";
import { Button } from "../../../ui/Button";
import { projectActivity } from "../ActivityHistory";
import type { RequestInspectionTarget } from "../ProcessPanel";
import { investigationResults } from "../contextView";
import {
  type SelectorKey,
  type SourcePickerDraft,
  sourceErrors,
} from "../eventTextSelection";
import { guidanceNames, saveGuidanceSet } from "../guidanceReview";
import { historyOutcome } from "../historyView";
import { activeRun, observedRun } from "../translationView";
import { useContextDraft } from "../useContextDraft";
import { useGuidedWorkflow } from "../useGuidedWorkflow";
import { useTranslationFlow } from "../useTranslationFlow";
import { completedTasks, reviewTasks } from "../progress";
import { type PendingPartId, pendingPart } from "../pending";
import { usePendingChanges } from "./usePendingChanges";
import { assistantWaiting, noHandoff } from "../../assistant/assistantTasks";
import { useAssistantSources } from "../../assistant/useAssistantTasks";
import { initialPosition, stagesFor } from "../workflow";

/** The operations setting up a game runs, in order. */
export const setupSteps = [
  "backup_source",
  "ace_extract",
  "prepare_game",
  "git_setup",
] as const;
export type SetupStep = (typeof setupSteps)[number];
import {
  type GuidedIntent,
  type GuidedProps,
  type Panel,
  actionKey,
  advancedCodes,
  fileCount,
  jobTime,
  runNotices,
} from "./model";
import { selectionNames } from "../../../ui/displayText";
import { childPath } from "../../../ui/displayPath";

/** How the footer names a run that ended without failing. */
const endings = {
  stopped: "Run stopped",
  interrupted: "Run interrupted",
  canceled: "Run canceled",
  cancelled: "Run canceled",
};

/** Shared state, derived values and actions behind every Guided task view. */
export function useGuidedWorkspace({
  project,
  state,
  translation,
  settings,
  openProject,
  intent,
  intentHandled,
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
  // A Live run started here that ends replaces an earlier run notice with its
  // outcome, so the footer never keeps saying an estimate was declined after
  // work finished. Older runs whose saved status is corrected after a restart
  // are not announced, and a Batch keeps its own provider monitoring, since
  // its local worker ends long before the provider does.
  const [opened] = useState(() => Date.now());
  const runStates = state.runs
    .filter((run) => !run.temporary && run.mode === "translate")
    .map((run) => `${run.id}:${run.status}`)
    .join(" ");
  useOnChange(runStates, (_, before) => {
    const earlier = new Map(
      before
        .split(" ")
        .filter(Boolean)
        .map((entry) => entry.split(":") as [string, string]),
    );
    const ended = state.runs.find(
      (run) =>
        ["ready", "running", "waiting"].includes(earlier.get(run.id) || "") &&
        !activeRun(run) &&
        Date.parse(run.created || "") >= opened,
    );
    // A failed run shows its reason on its task instead of reading as finished.
    if (ended && ended.status !== "failed" && !action.busy) {
      const outcome = historyOutcome(ended);
      const ending =
        endings[ended.status as keyof typeof endings] || "Run finished";
      // The footer already counts saved files; other outcomes need their detail.
      action.succeed(
        outcome.kind === "saved"
          ? `${ending}.`
          : `${ending} · ${outcome.detail || outcome.label}`,
        "run:finished",
      );
    }
  });
  const stages = stagesFor(state.engine);
  const position = initialPosition(state, translation);
  const stage = stages.find((item) => item.id === position.step)!;
  const selectedTask = stage.tasks.find((item) => item.id === position.task);
  const taskId = selectedTask?.id || "run";
  const taskView =
    taskId === "other-event-text" ? state.eventText.view : taskId;
  const taskIndex = stage.tasks.findIndex((item) => item.id === taskId);
  const showTaskTabs = stage.tasks.length > 1;
  const taskTabsId = `${stage.id}-tasks`;
  const [panel, setPanel] = useState<Panel>(null);
  const [speakerTab, setSpeakerTab] = useState("findings");
  const [editorAssets, setEditorAssets] = useState<string[] | null>(null);
  // Hosted tasks with their own action bar fill the Guided footer through this slot.
  const [taskFooter, setTaskFooter] = useState<HTMLDivElement | null>(null);
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
  const [comparisonReview, setComparisonReview] = useState(false);
  const [comparisonsAccepted, setComparisonsAccepted] = useState(false);
  const [inspection, setInspected] = useState<Job | null>(null);
  const [inspectionTarget, setInspectionTarget] =
    useState<RequestInspectionTarget>();
  // One stage's Run history opens over its task, so closing returns there.
  const [runHistory, setRunHistory] = useState<Phase | null>(null);
  const inspected = observedRun(
    inspection,
    state.runs.find((run) => run.id === inspection?.id),
  );
  const [started, setStarted] = useState<Record<string, Job>>({});
  // The files each apply from this visit wrote, by job: every translation task
  // has its own Apply, and one confirms only the files it applied.
  const [appliedFiles, setAppliedFiles] = useState<Record<string, string>>({});
  // The label each action had when clicked: an install turns its button into
  // Update, but its result still confirms the install.
  const [clickedLabels, setClickedLabels] = useState<Record<string, string>>(
    {},
  );

  const documentName = state.contextDocument;
  const setDocumentName = (name: string) => {
    void action.run(async () =>
      application.navigateGuided(project.id, { contextDocument: name }),
    );
  };
  const [setupNotice, setSetupNotice] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
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
  // The original backup the game folder already holds, offered to a project
  // without one, such as after the game was moved or copied.
  const storedOriginal = translation.storedOriginal;
  const baseline = preserved && !!translation.git?.configured;
  const job = state.run;
  const findings = state.speakerSetup;
  const scan = state.speakerScan;
  const discovery = state.contextSetup;
  const investigation = investigationResults(state);
  const investigationDone = investigation.every((row) => row.saved);
  const [setupCopiedOpen, setSetupCopiedOpen] = useState(false);
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
  const layoutFiles = state.files
    .filter((file) => selectedFiles.has(file.name))
    .map((file) => file.name);
  const enabledCodes = advancedCodes.filter(
    (key) => values.engine_options[key] === true,
  );
  // Translate saves edited source choices before it prepares an estimate.
  const advancedReady =
    enabledCodes.length > 0 &&
    !sourceErrors(state.eventText, values.engine_options).length;
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
  // Setup and Release show their own operations in the task, so the shared
  // operation row above the task leaves them out.
  const localOperation =
    !panel &&
    activeOperation &&
    ((taskId === "setup" &&
      [
        "backup_source",
        "prepare_game",
        "format_data",
        "format_plugins",
        "gameupdate",
        "git_setup",
      ].includes(activeOperation.action || "")) ||
      (taskId === "package" &&
        ["release", "release_patch"].includes(activeOperation.action || "")))
      ? activeOperation
      : null;
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
  const qaStatus = qa.status;
  const release = fields.release;
  const releaseAction = release.kind === "game" ? "release" : "release_patch";
  const releasePath = childPath(release.directory, release.name);
  const artifact = state.artifacts.find((item) => item.kind === release.kind);
  // Release checks its destination while it is typed, so Build never learns of
  // a rejected folder late; the name's own separator rule needs no read.
  const nameError = /[\\/]/.test(release.name)
    ? "Use a filename without folder separators. Choose the destination in Save in."
    : "";
  const destination = useRead(
    taskId === "package" &&
      !nameError &&
      release.directory.trim() &&
      release.name.trim()
      ? `${project.id}\n${releasePath}`
      : null,
    () => api.guided.releaseDestination(project.id, releasePath),
  );
  const destinationError = nameError || destination.value?.error || "";

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
  /** The current findings' recommendations replace the source choices. */
  const applyRecommendations = () =>
    action.run(
      async () => {
        await save();
        await draft.applyEventText();
      },
      "Source choices updated.",
      "event-text:recommendations",
    );
  const skipEventText = () =>
    stepTask(
      state.comparisons.status !== "not_needed" ? "variables" : "plugins",
    );
  /** Source choices save as the user moves on from them. */
  const saveSources = async (task: string) => {
    if ((await action.run(save, "", "event-text:save")).ok) stepTask(task);
  };
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
          title={`Back (${shortcutLabel.back})`}
          aria-keyshortcuts={shortcutKeys.back}
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
        {...(target === next() && {
          title: `Continue (${shortcutLabel.next})`,
          "aria-keyshortcuts": shortcutKeys.next,
        })}
        disabled={action.busy || draft.committing || context.committing}
        onClick={() => stepTask(target.id)}
      >
        {label ||
          "Continue to " +
            (stage.tasks.includes(target)
              ? // Mid-sentence, capitalized words lower but QA stays QA.
                target.title.replace(/\b([A-Z])(?=[a-z])/g, (letter) =>
                  letter.toLowerCase(),
                )
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
  // The Project tab that asked for a checkpoint, to return to afterwards.
  const checkpointReturn = useRef<"versions" | null>(null);
  const leaveCheckpoint = (action: string) => {
    const tab = checkpointReturn.current;
    if (action !== "checkpoint" || !tab) return;
    checkpointReturn.current = null;
    openProject(tab);
  };
  // The last executed review, so a sequence waiting on a review it opened
  // learns which operation the user's approval started.
  const executed = useRef<{ token: string; job: Job } | null>(null);
  const lastExecuted = () => executed.current;
  const execute = async (value: Preview) => {
    setAttemptedPreview(value.token);
    const result = await api.execute(project.id, value.token);
    setStarted((previous) => ({
      ...previous,
      [actionKey(value.action, value.options)]: result,
    }));
    executed.current = { token: value.token, job: result };
    if (value.action === "export_selected")
      setAppliedFiles((previous) => ({
        ...previous,
        [result.id]: value.paths.join("\n"),
      }));
    setPreview(null);
    leaveCheckpoint(value.action);
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
    action
      .run(
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
          if ((!result.confirmation || prepareBatch) && !inspectOnly) {
            await execute(result);
            return null;
          }
          return result;
        },
        "",
        actionKey(name, options),
      )
      // The review opens once the action and its refresh settle, so its
      // buttons start ready; until then the clicked control shows the wait.
      .then((outcome) => {
        if (outcome.ok && outcome.value) setPreview(outcome.value);
        return outcome;
      });
  // Re-applying a saved run's output opens its Apply review.
  const reapplyRun = async (runId: string) => {
    const options = { run_id: runId };
    const result = await preparePreview("export_selected", options);
    setPreviewRequest({ name: "export_selected", options });
    setInspectRelease(false);
    setPreview(result);
  };
  // A review the Project page asked for opens once, over the saved task.
  const openIntent = useEffectEvent((request: GuidedIntent) => {
    if (request.kind === "checkpoint")
      checkpointReturn.current = request.returnTo ?? null;
    const opened =
      request.kind === "checkpoint"
        ? review("checkpoint")
        : request.kind === "restore"
          ? review("runtime_restore", { publication: request.publication })
          : action.run(
              async () => {
                if (request.kind === "reapply") await reapplyRun(request.runId);
                else {
                  const run = state.runs.find(
                    (item) => item.id === request.runId,
                  );
                  if (!run) throw new Error("That run is no longer saved.");
                  setResume(run);
                }
              },
              "",
              request.kind,
            );
    void opened.finally(() => intentHandled?.());
  });
  useEffect(() => {
    if (intent) openIntent(intent);
  }, [intent]);
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
        if (preview) leaveCheckpoint(preview.action);
      },
      "",
      "review:cancel",
    );
  // A new translation's progress replaces the notice about an earlier run.
  const translateSelected = () => {
    if (!action.busy && runNotices.includes(action.key)) action.clear();
    translationFlow.start();
  };
  useEffect(() => {
    if (
      action.busy ||
      translationFlow.active ||
      panel ||
      inspection ||
      inspectionTarget ||
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
    variant: "default" | "primary" | "quiet" | "link" = "default",
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
    const finishedHere =
      current?.status === "complete" &&
      current.id === started[actionKey(name, options)]?.id;
    const appliedHere =
      name === "export_selected" &&
      finishedHere &&
      appliedFiles[current.id] === files?.join("\n");
    // Applying fitting closes its review and the page returns to scanning,
    // so the scan control confirms an apply from this visit.
    const fittingApplied = operationJob("rewrap_apply");
    const fittedHere =
      name === "rewrap_preview" &&
      fittingApplied?.status === "complete" &&
      fittingApplied.id === started["rewrap_apply"]?.id &&
      jobTime(fittingApplied) >= jobTime(current || {});
    const qaOperation = ["qa_prepare", "qa_status"].includes(name);
    // Release reports a finished build in its saved archive panel; only a
    // build from this visit also confirms beside its button.
    const releaseBuild = ["release", "release_patch"].includes(name);
    const builtHere = releaseBuild && finishedHere;
    // Prepare's stage rows record each preparation tool's outcome.
    const preparationTool = [
      "format_data",
      "format_plugins",
      "gameupdate",
    ].includes(name);
    // A tool row's own status says whether the tool is installed, the
    // editor search lists what it found, and fitting and QA rows state the
    // result of their scan or preparation.
    const toolChange =
      preparationTool ||
      [
        "inspector_install",
        "inspector_remove",
        "forge_install",
        "forge_remove",
        "editors",
        "rewrap_preview",
        "qa_prepare",
      ].includes(name);
    // A tool row reports only its latest change, so installing again
    // replaces the earlier removal's result.
    const toolCounterpart = (
      {
        inspector_install: "inspector_remove",
        inspector_remove: "inspector_install",
        forge_install: "forge_remove",
        forge_remove: "forge_install",
      } as Record<string, string>
    )[name];
    const superseded =
      !!toolCounterpart &&
      !!current &&
      jobTime(operationJob(toolCounterpart) || {}) > jobTime(current);
    // An update leaves the row's status as it was, so a tool change from
    // this visit still confirms beside its button.
    const toolDoneHere = finishedHere && !!toolCounterpart && !superseded;
    // Packing's label says whether the native data is current; a pack from
    // this visit also confirms beside its button.
    const packedHere = name === "ace_pack" && finishedHere;
    const display =
      superseded ||
      (current?.status === "complete" &&
        (publicationReview ||
          releaseBuild ||
          toolChange ||
          name === "ace_pack" ||
          (qaOperation && (!qa.current || current.result?.task !== qa.task))))
        ? undefined
        : current;
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
              ? `${typeof current.result?.files === "number" ? fileCount(current.result.files) : "Files"} reloaded from the game.`
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
    // Setup reports its operations in the task's step rows; a build
    // reports its progress beside its own button.
    if (localOperation?.action === name && !releaseBuild)
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
        {...(appliedHere
          ? { notice: "Saved translations applied." }
          : fittedHere
            ? {
                notice: "Rewrapped lines applied.",
              }
            : toolDoneHere
              ? {
                  // Short, so the row's buttons stay side by side.
                  notice: name.endsWith("_remove")
                    ? "Removed."
                    : clickedLabels[name] === "Update"
                      ? "Updated."
                      : "Installed.",
                }
              : packedHere
                ? { notice: "Native data packed." }
                : builtHere
                  ? {
                      notice: `${name === "release" ? "Game" : "Patch"} ZIP saved.`,
                    }
                  : preparationTool && finishedHere
                    ? {
                        notice:
                          name === "gameupdate"
                            ? "GameUpdate files created."
                            : "Formatted.",
                      }
                    : {})}
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
        onClick={() => {
          setClickedLabels((previous) => ({ ...previous, [name]: label }));
          void review(name, options, files);
        }}
      />
    );
  };
  const workingFileActions = () => (
    <>
      <ActionRow
        title="Translated folder"
        description="Inspect or copy its JSON files. Some files may contain partial progress."
      >
        <ActionControl
          label="Open translated folder"
          icon={<FolderOpen size={16} aria-hidden="true" />}
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
  // Whether a copied task waits on the assistant, from the shared list.
  const assistantSources = useAssistantSources();
  const handoff = (kind: AssistantTaskKind) =>
    assistantSources ? assistantWaiting(kind, assistantSources) : noHandoff;
  const copyTask = (
    name: string,
    label: string,
    variant: "default" | "primary" | "quiet" | "link" = "default",
    copied = "Task copied. Return to its saved results when your assistant finishes.",
  ) => (
    <ActionControl
      label={label}
      variant={variant}
      disabled={disabled}
      {...feedback("copy:" + name, "Copying…")}
      // When the results a copied task asked for arrive, "paste it into your
      // assistant" no longer describes a next step.
      {...(name === "setup" &&
        setupCopiedOpen &&
        investigationDone && { notice: "" })}
      onClick={() =>
        action.run(
          async () => {
            if (name === "setup") setSetupCopiedOpen(!investigationDone);
            await save();
            await window.dazedtl.copyText(
              (await api.guided.skill(project.id, name)).text,
            );
          },
          name === "setup"
            ? "Task copied. Paste it into your assistant."
            : copied,
          "copy:" + name,
        )
      }
    />
  );
  const inspect = (item: Job | null, target?: RequestInspectionTarget) => {
    const current = document.activeElement;
    setInspectorReturnFocus(current instanceof HTMLElement ? current : null);
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
      // Saving creates missing files and writes drafts; otherwise it is a no-op.
      names.some(
        (name) => context.drafts[name] || !discovery.documents[name]?.exists,
      )
        ? "Guidance saved."
        : "Guidance is already saved.",
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
  // A check is current while its widths and options are the saved ones.
  const fittingCurrent =
    !!state.readiness.layout_scan &&
    !draft.dirty &&
    fittingSettingsSaved &&
    !!fitting;
  const fittingEligible = fitting
    ? fitting.changes_found - fitting.overflow_skipped
    : 0;
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
  // The file choice as one row, for panels that hold a task's other settings;
  // a short selection names its files.
  const fileRow = (
    names: readonly string[] = values.selected,
    scope: "database" | "dialogue" | null = null,
  ) => (
    <ActionRow
      title={`${fileCount(names.length)} selected`}
      description={selectionNames(names) || undefined}
    >
      <Button disabled={disabled} onClick={() => chooseFiles(scope)}>
        Choose files
      </Button>
    </ActionRow>
  );
  const fileSummary = (
    names: readonly string[] = values.selected,
    scope: "database" | "dialogue" | null = null,
  ) => <ActionList>{fileRow(names, scope)}</ActionList>;
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
  // Setting up backs up the original, prepares the game files and saves the
  // version in sequence from one click. Each step keeps its own preview and
  // execution checks, and a replacement backup keeps its review. A step that
  // fails, stops or whose review is declined ends the sequence; the next
  // click resumes from the first step that is not done. The sequence has its
  // own action, so navigation and Stop stay available while it runs.
  const setupAction = useAction({ after: application.settle });
  const gitConfigured = !!translation.git?.configured;
  const setupStep: SetupStep | null = !preserved
    ? "backup_source"
    : aceNeedsExport
      ? "ace_extract"
      : !(preparationComplete || gitConfigured)
        ? "prepare_game"
        : !gitConfigured
          ? "git_setup"
          : null;
  const setupJobs = Object.fromEntries(
    setupSteps.map((name) => [name, operationJob(name)]),
  ) as Record<SetupStep, Job | undefined>;
  const setupWorking = setupSteps.some((name) =>
    ["ready", "running", "waiting"].includes(setupJobs[name]?.status || ""),
  );
  // Why the step setup would run next stopped, until a newer attempt starts.
  const stoppedStage = preparation.stages.find((stage) =>
    ["failed", "interrupted", "stopped"].includes(stage.status),
  );
  // Preparation's stage rows reset when the game files change, retiring an
  // older failure that no longer applies.
  const stoppedJob =
    setupStep === "backup_source" ||
    setupStep === "ace_extract" ||
    setupStep === "git_setup"
      ? setupJobs[setupStep]
      : undefined;
  const setupFailure =
    setupStep === "prepare_game"
      ? stoppedStage
        ? `${stoppedStage.label}: ${stoppedStage.message || "it did not finish."}`
        : ""
      : stoppedJob &&
          ["failed", "interrupted", "stopped"].includes(stoppedJob.status)
        ? stoppedJob.message || "This step did not finish."
        : "";
  // What a running sequence (setup, pending changes) reads after each
  // observation.
  const observedState = {
    step: setupStep,
    failure: setupFailure,
    preview: preview?.token ?? null,
    taskId,
    // The backend starts the next step only once no worker is running.
    running,
    storedOriginal: storedOriginal?.id,
    // Finished operations by id, with how they ended.
    finished: new Map(
      [...state.operations, ...translation.jobs]
        .filter(
          (item) => !["ready", "running", "waiting"].includes(item.status),
        )
        .map((item) => [
          item.id,
          { status: item.status, message: item.message || "" },
        ]),
    ),
  };
  const latestObserved = useRef(observedState);
  const observedWaiters = useRef(new Set<() => void>());
  useEffect(() => {
    latestObserved.current = observedState;
    for (const check of observedWaiters.current) check();
  });
  const whenObserved = (ready: (value: typeof observedState) => boolean) =>
    new Promise<void>((resolve) => {
      const check = () => {
        if (!ready(latestObserved.current)) return;
        observedWaiters.current.delete(check);
        resolve();
      };
      observedWaiters.current.add(check);
      check();
    });
  /** How an operation started here ended, once no worker is running. */
  const whenFinished = async (id: string) => {
    await whenObserved((value) => !value.running && value.finished.has(id));
    return latestObserved.current.finished.get(id)!;
  };
  const ownState = <T extends { projectId: string }>(value?: T | null) =>
    value && value.projectId === project.id ? value : null;
  // What each task has reviewed and ready to go into the game.
  const pendingInput = {
    plugins: ownState(application.snapshot?.plugins)?.counts.ready || 0,
    images: ownState(application.snapshot?.images)?.counts.selectedReady || 0,
    rewraps: fittingCurrent ? fittingEligible : 0,
  };
  const pending = usePendingChanges({
    projectId: project.id,
    settle: application.settle,
    guided: () => ({ name: "rewrap_apply", options: layoutOptions }),
    preparePreview,
    execute,
    lastExecuted,
    whenFinished,
  });
  /**
   * Opens the review of one task's ready work; Images passes its count of
   * translated images.
   */
  const openPending = (
    only: PendingPartId,
    choice: { images?: number } = {},
  ) => {
    const part = pendingPart(only, {
      ...pendingInput,
      images: choice.images ?? pendingInput.images,
    });
    return part && pending.open(part, only);
  };
  /** A task's Review & apply, opening the pending review for its part. */
  const reviewPending = ({
    only,
    label,
    variant = "primary",
    blocked = false,
    choice,
  }: {
    only: PendingPartId;
    label: string;
    variant?: "primary" | "default";
    blocked?: boolean | string;
    choice?: Parameters<typeof openPending>[1];
  }) => (
    <ActionControl
      label={label}
      variant={variant}
      disabled={disabled || pending.busy || !!blocked}
      disabledReason={typeof blocked === "string" ? blocked : ""}
      pendingText="Preparing the review…"
      {...pending.feedback(only)}
      onClick={() => void openPending(only, choice)}
    />
  );
  const startSetup = () =>
    setupAction.run(
      async () => {
        const tried = new Set<SetupStep>();
        let job: Job | undefined;
        for (;;) {
          const { step, failure, finished } = latestObserved.current;
          if (!step) break;
          if (tried.has(step))
            throw new Error(
              failure ||
                (job && finished.get(job.id)?.message) ||
                "Setup stopped before this step finished.",
            );
          tried.add(step);
          // A game folder that already holds its original takes it over
          // instead of saving its current files as the original.
          const stored = latestObserved.current.storedOriginal;
          const name =
            step === "backup_source" && stored ? "use_source_backup" : step;
          const options =
            step === "git_setup"
              ? setupOptions()
              : stored && name === "use_source_backup"
                ? { backup_id: stored }
                : {};
          const result = await preparePreview(name, options);
          setPreviewRequest({ name, options });
          if (result.confirmation) {
            // A replacement backup keeps its review; the sequence continues
            // once the user approves it and ends if they cancel.
            executed.current = null;
            setInspectRelease(false);
            setPreview(result);
            await whenObserved((value) => value.preview === result.token);
            await whenObserved((value) => value.preview !== result.token);
            const approved = lastExecuted();
            if (approved?.token !== result.token) return;
            job = approved.job;
          } else {
            await execute(result);
            job = lastExecuted()!.job;
          }
          // The step's records can update before its worker exits.
          const id = job.id;
          await whenObserved(
            (value) =>
              !value.running && (value.finished.has(id) || value.step !== step),
          );
        }
        if (latestObserved.current.step === null) {
          // A version saved before this run is not news.
          setSetupNotice(
            tried.has("git_setup")
              ? `Version ${fields.version.trim()} saved. Setup complete.`
              : "Setup complete.",
          );
          if (latestObserved.current.taskId === "setup")
            await navigate("context", "names");
        }
      },
      "",
      "setup",
    );
  const setupOptions = () => ({
    version: fields.version,
    original: fields.untranslated ? "" : fields.original,
    untranslated: fields.untranslated,
  });
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
          ? "Continue to other event text"
          : current.logicalPhase === "advanced" &&
              state.comparisons.status !== "not_needed"
            ? "Review comparisons"
            : "Continue to plugin files"}
    </Button>
  );
  const completed = completedTasks(state, translation, {
    values,
    widthsDirty,
    plugins: application.snapshot?.plugins,
    images: application.snapshot?.images,
  });
  const needsReview = reviewTasks({
    pluginsForeign: application.snapshot?.pluginsForeign,
    imagesForeign: application.snapshot?.imagesForeign,
  });
  const applySpeakerControl = findings.status === "ready" && (
    <ActionControl
      label={
        draft.dirty || state.optionsDraft
          ? "Save edits & use findings"
          : "Use investigated rules"
      }
      disabled={disabled}
      pending={speakerAction.busy}
      pendingText="Saving rules…"
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
    openProject,
    handoff,
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
    editorAssets,
    setEditorAssets,
    taskFooter,
    setTaskFooter,
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
    comparisonReview,
    setComparisonReview,
    comparisonsAccepted,
    setComparisonsAccepted,
    setInspected,
    inspectionTarget,
    setInspectionTarget,
    inspected,
    runHistory,
    setRunHistory,
    started,
    documentName,
    setDocumentName,
    setupNotice,
    bodyRef,
    headingRef,
    inspectorReturnFocus,
    reapplyRun,
    running,
    sourceBackup,
    storedOriginal,
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
    stopOperation,
    qaTask,
    qaJob,
    qa,
    qaStatus,
    whenFinished,
    release,
    releaseAction,
    releasePath,
    destinationError,
    destinationPending: destination.pending,
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
    applyRecommendations,
    saveSources,
    skipEventText,
    advance,
    back,
    previous,
    next,
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
    widths,
    fileSummary,
    fileRow,
    formatActions,
    preparation,
    preparationComplete,
    aceNeedsExport,
    gitConfigured,
    setupStep,
    setupJobs,
    setupFailure,
    setupAction,
    setupWorking,
    startSetup,
    pending,
    openPending,
    reviewPending,
    fittingCurrent,
    fittingEligible,
    applyRun,
    nextRun,
    completed,
    needsReview,
    applySpeakerControl,
    fields,
  };
}

export type GuidedWorkspace = ReturnType<typeof useGuidedWorkspace>;
