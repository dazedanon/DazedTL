import { useRef, useState } from "react";
import { ArrowRight, Check, Folder, FolderOpen, X } from "lucide-react";
import { api } from "../../api/client";
import {
  ACTIONS,
  type ActionName,
  type AppState,
  type Job,
  type Project,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { flushDrafts } from "../../state/leaveGuards";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { HelpPopover } from "../../ui/HelpPopover";
import { JobStatus } from "../../ui/JobStatus";
import { Notice } from "../../ui/Notice";
import { PageBody, PageHeader, PageLayout } from "../../ui/PageLayout";
import { PathText } from "../../ui/PathText";
import { Section } from "../../ui/Section";
import { StatusIcon } from "../../ui/StatusIcon";
import { TabPanel, Tabs } from "../../ui/Tabs";
import { displayLabels, displayMarks } from "../../ui/displayStatus";
import { useRefocus } from "../../ui/useRefocus";
import { engineLabel, selectionNames, sentence } from "../../ui/displayText";
import { AssistantTaskList } from "../assistant/AssistantTaskList";
import { useAssistantTasks } from "../assistant/useAssistantTasks";
import { ActivityHistory } from "../guided/ActivityHistory";
import type { GuidedProgress, projectAmounts } from "../guided/progress";
import { RunInspector } from "../guided/RunInspector";
import { QaCoverageReport } from "../guided/TextQa";
import { canResumeRun, observedRun } from "../guided/translationView";
import type { GuidedIntent } from "../guided/workspace/model";
import { RequestsPanel } from "../translation/RequestsPanel";
import { VersionsPanel } from "../translation/VersionsPanel";
import type { SettingsSection } from "../settings/Settings";
import { CheckpointsPanel } from "./CheckpointsPanel";
import { guidedEngines, methodLabels } from "./MethodDialog";

export type ProjectTab = "status" | "history" | "checkpoints";
/** What removing a game from the recent list does, wherever it is offered. */
export const removeHint =
  "Remove from list. Opening the game again brings it back with its work.";
type Amounts = ReturnType<typeof projectAmounts>;

/**
 * The game's own page: where it stands, its history and its checkpoints.
 * Both translation methods share these tools here.
 */
export default function ProjectPage({
  state,
  busy,
  open,
  select,
  recent,
  remove,
  report,
  progress,
  amounts,
  tab,
  onTab,
  historyQuery,
  openTask,
  openTranslation,
  chooseMethod,
  settings,
  openGuided,
}: {
  state: AppState;
  busy: boolean;
  open: () => void;
  select: (id: string) => void;
  /** The recent list, without games being removed. */
  recent: Project[];
  remove: (id: string) => void;
  report: (error: unknown) => void;
  progress: GuidedProgress | null;
  amounts: Amounts | null;
  tab: ProjectTab;
  onTab: (tab: ProjectTab) => void;
  /** A search the History tab opens with, such as one stage's runs. */
  historyQuery?: string;
  openTask: (step: string, task: string) => void;
  openTranslation: (view?: "images") => void;
  chooseMethod: () => void;
  /** Opens Settings, at a section when one is given. */
  settings: (section?: SettingsSection) => void;
  /** Opens Translation for a review that belongs to the Guided workspace. */
  openGuided: (intent: GuidedIntent) => void;
}) {
  const project = state.project;
  if (!project)
    return (
      <NoProject
        recent={recent}
        busy={busy}
        open={open}
        select={select}
        remove={remove}
      />
    );
  const available = !!project.available;
  return (
    <PageLayout variant="editor" className="project-page" aria-label="Project">
      <PageHeader
        title={project.name}
        description={
          <span className="path-line">
            <span>
              {engineLabel(project.engine_label || project.engine)} ·{" "}
              {project.method
                ? methodLabels[project.method]
                : "No method chosen"}{" "}
              ·
            </span>
            <PathText path={project.source} />
          </span>
        }
        actions={
          <div className="actions">
            {/* Only RPG Maker MV/MZ and Ace games have another method to
                switch to once Assistant-led is chosen. */}
            {(project.method === "guided" ||
              (project.method === "len" &&
                guidedEngines.includes(project.engine))) && (
              <Button
                variant="quiet"
                disabled={busy || !available}
                onClick={chooseMethod}
              >
                Change method
              </Button>
            )}
            <Button
              disabled={!available}
              onClick={() => window.dazedtl.openFolder("project").catch(report)}
            >
              <FolderOpen size={16} aria-hidden="true" />
              Open folder
            </Button>
          </div>
        }
      />
      <div className="frame-row">
        <Tabs
          id="project"
          label="Project sections"
          value={tab}
          onChange={onTab}
          items={[
            { id: "status", label: "Status" },
            { id: "history", label: "History", disabled: !available },
            { id: "checkpoints", label: "Checkpoints", disabled: !available },
          ]}
        />
      </div>
      <TabPanel id="project" value={tab}>
        {tab === "status" && (
          <ProjectStatus
            state={state}
            project={project}
            busy={busy}
            open={open}
            progress={progress}
            amounts={amounts}
            openTask={openTask}
            openTranslation={openTranslation}
            chooseMethod={chooseMethod}
            settings={settings}
          />
        )}
        {tab === "history" && (
          <ProjectHistory
            key={historyQuery}
            project={project}
            query={historyQuery}
            openGuided={openGuided}
          />
        )}
        {tab === "checkpoints" && (
          <ProjectCheckpoints
            project={project}
            openTask={openTask}
            openGuided={openGuided}
          />
        )}
      </TabPanel>
    </PageLayout>
  );
}

function ProjectStatus({
  state,
  project,
  busy,
  open,
  progress,
  amounts,
  openTask,
  openTranslation,
  chooseMethod,
  settings,
}: {
  state: AppState;
  project: Project;
  busy: boolean;
  open: () => void;
  progress: GuidedProgress | null;
  amounts: Amounts | null;
  openTask: (step: string, task: string) => void;
  openTranslation: (view?: "images") => void;
  chooseMethod: () => void;
  settings: (section?: SettingsSection) => void;
}) {
  const operation = project.operation;
  const active =
    !!operation && ["ready", "running", "waiting"].includes(operation.status);
  const guided = project.method === "guided" && progress;
  // The latest operation shows once. Guided's card names the next task, so
  // the operation sits beside it; every other card is the operation itself.
  const beside = guided && operation;
  // One Continue: the next required task, or the last opened task once every
  // required task is done.
  const target = guided ? progress.next || progress.last : null;
  const assistantTasks = useAssistantTasks();
  const assistantList = project.available && (
    <AssistantTaskList
      projectId={project.id}
      tasks={assistantTasks}
      busy={busy}
      open={(task) =>
        project.method === "guided"
          ? openTask(task.place.step, task.place.task)
          : openTranslation("images")
      }
    />
  );
  const primary = !project.available ? (
    <Button variant="primary" disabled={busy || state.running} onClick={open}>
      {project.next_label}
    </Button>
  ) : !project.method ? (
    <Button variant="primary" disabled={busy} onClick={chooseMethod}>
      Choose translation method
    </Button>
  ) : guided && target ? (
    <Button
      variant="primary"
      disabled={busy}
      onClick={() => openTask(target.step, target.task)}
    >
      {/* Nothing done yet is a start, not a return to saved work. */}
      {!progress.stages.some((stage) => stage.done)
        ? "Start"
        : progress.next
          ? "Continue"
          : "Resume"}
      : {target.title}
      <ArrowRight size={15} aria-hidden="true" />
    </Button>
  ) : (
    <Button variant="primary" disabled={busy} onClick={() => openTranslation()}>
      Open {methodLabels[project.method]}
      <ArrowRight size={15} aria-hidden="true" />
    </Button>
  );
  return (
    <>
      <PageBody className="project-status">
        {beside && active && <JobStatus job={beside} />}
        {!project.available || !project.method ? (
          <ActionList>
            <ActionRow
              title={
                !project.available
                  ? project.status
                  : "Choose how to translate this game"
              }
              description={
                !project.available
                  ? project.detail
                  : "Guided steps walk through each stage with estimates; Assistant-led hands the whole game to your coding assistant."
              }
            />
          </ActionList>
        ) : guided ? (
          <>
            <ActionList>
              <ActionRow
                label={
                  progress.next ? (
                    <>
                      <span className="project-next-stage">
                        Next step · {progress.next.stage}
                      </span>
                      <strong>{progress.next.title}</strong>
                      <small>{progress.next.description}</small>
                      {progress.last && (
                        <Button
                          variant="link"
                          className="project-last-opened"
                          disabled={busy}
                          onClick={() =>
                            openTask(progress.last!.step, progress.last!.task)
                          }
                        >
                          Last opened: {progress.last.title}
                        </Button>
                      )}
                    </>
                  ) : (
                    <>
                      <span className="project-next-stage">Next step</span>
                      <strong>Required tasks are done</strong>
                      <small>
                        Build a release when the translation is ready.
                      </small>
                    </>
                  )
                }
              />
            </ActionList>
            {assistantList}
            {amounts && <ProjectAmounts amounts={amounts} />}
            <Section title="Tasks" className="project-tasks-section">
              <ol className="project-stages">
                {progress.stages.map((stage, index) => (
                  <li key={stage.id}>
                    <h3>
                      <span
                        className="guided-stage-marker"
                        data-state={
                          stage.complete
                            ? "done"
                            : stage.tasks.some((task) => task.done)
                              ? "started"
                              : undefined
                        }
                        aria-hidden="true"
                      >
                        {stage.complete ? (
                          <Check size={12} strokeWidth={3} />
                        ) : (
                          index + 1
                        )}
                      </span>
                      {stage.short}
                      {/* With one required task, the mark already says it all. */}
                      {stage.total > 1 && (
                        <span className="project-stage-count">
                          {stage.done}/{stage.total}
                        </span>
                      )}
                    </h3>
                    <ul>
                      {stage.tasks.map((task) => (
                        <li key={task.id}>
                          {task.review ? (
                            <StatusIcon
                              status={displayMarks.needs_review}
                              label={displayLabels.needs_review}
                              size={14}
                            />
                          ) : task.done || !task.optional ? (
                            <StatusIcon
                              status={task.done ? "done" : "idle"}
                              label={task.done ? "Complete" : "Not done"}
                              size={14}
                            />
                          ) : (
                            <span className="project-task-mark" />
                          )}
                          {/* Inline, so Optional wraps with a long title. */}
                          <span>
                            <Button
                              variant="link"
                              disabled={busy}
                              aria-current={
                                task.id === target?.task ? "step" : undefined
                              }
                              onClick={() => openTask(stage.id, task.id)}
                            >
                              {task.title}
                            </Button>
                            {(task.review || (task.optional && !task.done)) && (
                              <>
                                {" "}
                                <span className="project-task-optional">
                                  {task.review
                                    ? displayLabels.needs_review
                                    : "Optional"}
                                </span>
                              </>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ol>
            </Section>
          </>
        ) : (
          <ActionList>
            <ActionRow
              label={
                <>
                  <span className="project-next-stage">
                    {methodLabels[project.method]}
                  </span>
                  {operation ? (
                    <JobStatus job={operation} />
                  ) : (
                    <>
                      <strong>{project.status}</strong>
                      {project.detail && <small>{project.detail}</small>}
                    </>
                  )}
                </>
              }
            />
          </ActionList>
        )}
        {project.method && project.method !== "guided" && assistantList}
        {beside && !active && (
          <p className="project-activity">
            Last activity: {beside.label}
            {beside.status !== "complete" && ` · ${sentence(beside.status)}`}
          </p>
        )}
        {!state.provider_ready && (
          <Notice tone="warning">
            <span>Choose a connection and model before API translation.</span>
            <Button
              variant="link"
              disabled={busy}
              onClick={() => settings("api")}
            >
              Open Settings
            </Button>
          </Notice>
        )}
      </PageBody>
      <ActionBar feedback={null}>{primary}</ActionBar>
    </>
  );
}

/** Amounts appear once there is something to count; zeroes stay hidden. */
function ProjectAmounts({ amounts }: { amounts: Amounts }) {
  const figures = [
    amounts.done > 0 && {
      key: "lines",
      value:
        amounts.total !== null
          ? `${amounts.done.toLocaleString()} / ${amounts.total.toLocaleString()}`
          : amounts.done.toLocaleString(),
      label: "lines translated",
    },
    amounts.outputs > 0 && {
      key: "applied",
      value: `${amounts.applied} / ${amounts.outputs}`,
      label: "files applied",
    },
    amounts.cost > 0 && {
      key: "cost",
      value: `$${amounts.cost.toFixed(2)}`,
      label: "recorded cost",
      help: "The engine's per-file cost receipts and OpenRouter Batch charges. Other Batch charges appear only in your provider's billing.",
    },
  ].filter(Boolean) as {
    key: string;
    value: string;
    label: string;
    help?: string;
  }[];
  if (!figures.length) return null;
  return (
    <dl className="project-amounts">
      {figures.map((figure) => (
        <div key={figure.key}>
          <dt>
            {figure.label}
            {figure.help && (
              <>
                {" "}
                <HelpPopover label={figure.label}>{figure.help}</HelpPopover>
              </>
            )}
          </dt>
          <dd>{figure.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The label History lists a text batch it restores under, or "". */
function restorable(kind: string) {
  const row = Object.hasOwn(ACTIONS, kind)
    ? ACTIONS[kind as ActionName]
    : undefined;
  return row?.restorable ? row.label : "";
}

function ProjectHistory({
  project,
  query,
  openGuided,
}: {
  project: Project;
  query?: string;
  openGuided: (intent: GuidedIntent) => void;
}) {
  const application = useApplication();
  const { snapshot } = application;
  const guided = snapshot?.guided,
    translation = snapshot?.translation;
  const [footer, setFooter] = useState<HTMLDivElement | null>(null);
  const [inspection, setInspection] = useState<Job | null>(null);
  // Undoing a batch through its checkpoint runs here in one click.
  const undo = useAction({ observer: application });
  const [undoJob, setUndoJob] = useState("");
  if (!translation || translation.projectId !== project.id) return null;
  if (project.method !== "guided" || guided?.projectId !== project.id)
    return (
      <>
        <PageBody>
          <RequestsPanel state={translation} />
        </PageBody>
        <ActionBar feedback={null}>{null}</ActionBar>
      </>
    );
  const inspected = observedRun(
    inspection,
    guided.runs.find((run) => run.id === inspection?.id),
  );
  const baseline = !!translation.git?.configured;
  // A text QA batch, a glossary fix batch from before Text QA took the
  // glossary over, a playtest fix batch or a fit to new Line widths restores
  // from here, once no later batch in the game changed the same files.
  const publication =
    !!restorable(inspected?.action || "") &&
    inspected?.status === "complete" &&
    typeof inspected.result?.publication === "string"
      ? inspected.result.publication
      : "";
  // Preparing the current QA task records what QA did not cover; the Text
  // QA page leaves it out, as each part has its own owner.
  const qaRecord =
    inspected?.action === "qa_prepare" &&
    !!guided.readiness.qa.task &&
    inspected.result?.task === guided.readiness.qa.task;
  const batch = guided.readiness.publications.find(
    (row) => row.id === publication,
  );
  const blocker = batch?.blocker;
  const shared =
    blocker &&
    selectionNames(blocker.files.map((path) => path.split("/").pop()!));
  const restoreBlocked = !batch
    ? "History restores only its ten newest text batches."
    : batch.state === "restored"
      ? "This batch is already restored."
      : !blocker
        ? ""
        : blocker.reason
          ? blocker.reason
          : restorable(blocker.kind)
            ? `Restore the later “${restorable(blocker.kind)}” first; it also changed ${shared}.`
            : `A later Apply replaced ${shared}, so this batch can’t be restored.`;
  const undone = guided.operations.find((job) => job.id === undoJob);
  return (
    <>
      <PageBody className="history-host-body">
        <ActivityHistory
          state={guided}
          translation={translation}
          inspect={setInspection}
          initialQuery={query}
          footerTarget={footer}
        />
      </PageBody>
      <ActionBar
        feedback={<div ref={setFooter} className="history-host-footer" />}
      >
        {null}
      </ActionBar>
      {inspected && (
        <RunInspector
          key={`${project.id}:${inspected.id}`}
          projectId={project.id}
          job={inspected}
          close={() => setInspection(null)}
          disabled={!baseline}
          details={
            qaRecord && (
              <QaCoverageReport
                load={() => api.guided.qaReport(project.id)}
                labels={
                  snapshot?.plugins?.projectId === project.id
                    ? snapshot.plugins.labels
                    : undefined
                }
              />
            )
          }
          reapply={async (job) =>
            openGuided({ kind: "reapply", runId: job.id })
          }
          actions={
            publication ? (
              <ActionList compact>
                <ActionRow
                  label={
                    <small>
                      {inspected?.action === "qa_apply"
                        ? "Put back the text these corrections replaced; Text QA then offers them again."
                        : inspected?.action === "glossary_apply"
                          ? "Put back the text these glossary fixes replaced."
                          : inspected?.action === "playtest_fix"
                            ? "Put back the game's fixes plugin and main.js as they were before these fixes."
                            : inspected?.action === "fit_text"
                              ? "Put back the text as it was wrapped before these Line widths."
                              : "Apply the corrections this batch undid again."}
                    </small>
                  }
                >
                  {batch?.undo ? (
                    <ActionControl
                      label="Undo"
                      pendingText="Undoing…"
                      pending={undo.busy}
                      error={undo.error}
                      // A finished undo says so; the batch then reads restored.
                      job={undone?.status === "complete" ? undefined : undone}
                      notice={undone?.status === "complete" ? "Undone." : ""}
                      disabled={!baseline || !!restoreBlocked || undo.busy}
                      disabledReason={restoreBlocked}
                      onClick={() =>
                        void undo.run(async () => {
                          await flushDrafts();
                          const preview = await api.preview(
                            project.id,
                            "runtime_undo",
                            undefined,
                            { publication },
                          );
                          setUndoJob(
                            (await api.execute(project.id, preview.token)).id,
                          );
                        })
                      }
                    />
                  ) : (
                    <ActionControl
                      label="Review restore"
                      disabled={!baseline || !!restoreBlocked}
                      disabledReason={restoreBlocked}
                      onClick={() =>
                        openGuided({ kind: "restore", publication })
                      }
                    />
                  )}
                </ActionRow>
              </ActionList>
            ) : (
              canResumeRun(inspected) && (
                <ActionList compact>
                  <ActionRow
                    label={
                      <small>
                        Continue Live with this run’s saved settings.
                      </small>
                    }
                  >
                    <Button
                      onClick={() =>
                        openGuided({ kind: "resume", runId: inspected.id })
                      }
                    >
                      Review resume
                    </Button>
                  </ActionRow>
                </ActionList>
              )
            )
          }
        />
      )}
    </>
  );
}

function ProjectCheckpoints({
  project,
  openTask,
  openGuided,
}: {
  project: Project;
  openTask: (step: string, task: string) => void;
  openGuided: (intent: GuidedIntent) => void;
}) {
  const { snapshot } = useApplication();
  const translation = snapshot?.translation;
  const [target, setTarget] = useState<HTMLDivElement | null>(null);
  if (!translation || translation.projectId !== project.id) return null;
  const guided = project.method === "guided";
  return (
    <>
      <PageBody>
        <CheckpointsPanel
          project={project}
          state={translation}
          update={
            <VersionsPanel
              guided={guided}
              project={project}
              state={translation}
              onPrepare={guided ? () => openTask("setup", "setup") : undefined}
              openTask={guided ? openTask : undefined}
              openFiles={
                guided
                  ? (group, files) =>
                      openGuided({ kind: "select", group, files })
                  : undefined
              }
              actionTarget={target}
            />
          }
        />
      </PageBody>
      <ActionBar feedback={null}>
        <div ref={setTarget} className="action-bar-slot" />
      </ActionBar>
    </>
  );
}

/** With no game open, the page offers to open one or a recent project. */
function NoProject({
  recent: all,
  busy,
  open,
  select,
  remove,
}: {
  recent: Project[];
  busy: boolean;
  open: () => void;
  select: (id: string) => void;
  remove: (id: string) => void;
}) {
  const recent = all.slice(0, 5);
  const list = useRef<HTMLDivElement>(null);
  const refocus = useRefocus(() => [
    ...(list.current?.querySelectorAll<HTMLElement>("button:not(:disabled)") ||
      []),
  ]);
  return (
    <PageLayout className="project-page" aria-label="Project">
      <PageHeader title="Project" />
      <ActionList>
        <ActionRow
          label={
            <span className="project-welcome">
              <span className="project-welcome-cat" aria-hidden="true" />
              <span>
                <strong>No project open</strong>
                <small>
                  {`Open a game to get started${recent.length ? ", or choose a recent project below." : "."}`}
                </small>
              </span>
            </span>
          }
        >
          <Button variant="primary" disabled={busy} onClick={open}>
            <FolderOpen size={16} aria-hidden="true" />
            Open a game
          </Button>
        </ActionRow>
      </ActionList>
      {!!recent.length && (
        <Section title="Recent projects" className="project-recents">
          <div ref={list} className="project-recent-list">
            {recent.map((item) => (
              <div key={item.id} className="project-recent">
                <Button disabled={busy} onClick={() => select(item.id)}>
                  <Folder size={17} aria-hidden="true" />
                  <span>
                    <strong>{item.name}</strong>
                    <small>
                      <PathText path={item.source} />
                    </small>
                  </span>
                  <ArrowRight size={15} aria-hidden="true" />
                </Button>
                <Button
                  variant="quiet"
                  className="project-recent-remove"
                  aria-label={`Remove ${item.name} from the list`}
                  title={removeHint}
                  disabled={busy}
                  onClick={(event) => {
                    refocus(event.currentTarget);
                    remove(item.id);
                  }}
                >
                  <X size={15} aria-hidden="true" />
                </Button>
              </div>
            ))}
          </div>
        </Section>
      )}
    </PageLayout>
  );
}
