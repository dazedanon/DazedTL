import { useState } from "react";
import { ArrowRight, Check, Folder, FolderOpen } from "lucide-react";
import type { AppState, Job, Project } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { ActionBar } from "../../ui/ActionBar";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { JobStatus } from "../../ui/JobStatus";
import { Notice } from "../../ui/Notice";
import { PageBody, PageHeader, PageLayout } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { StatusIcon } from "../../ui/StatusIcon";
import { TabPanel, Tabs } from "../../ui/Tabs";
import { engineLabel } from "../../ui/displayText";
import { ActivityHistory } from "../guided/ActivityHistory";
import type { GuidedProgress } from "../guided/progress";
import { RunInspector } from "../guided/RunInspector";
import { canResumeRun, observedRun } from "../guided/translationView";
import type { GuidedIntent } from "../guided/workspace/model";
import { BackupsPanel } from "../translation/BackupsPanel";
import { RequestsPanel } from "../translation/RequestsPanel";
import { VersionsPanel } from "../translation/VersionsPanel";
import { methodLabels } from "./MethodDialog";

export type ProjectTab = "status" | "history" | "versions" | "backups";

const sentence = (value: string) =>
  value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ");

/**
 * The game's own page: where it stands, its history, game updates and
 * backups. Both translation methods share these tools here.
 */
export default function ProjectPage({
  state,
  busy,
  open,
  select,
  report,
  progress,
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
  report: (error: unknown) => void;
  progress: GuidedProgress | null;
  tab: ProjectTab;
  onTab: (tab: ProjectTab) => void;
  /** A search the History tab opens with, such as one stage's runs. */
  historyQuery?: string;
  openTask: (step: string, task: string) => void;
  openTranslation: () => void;
  chooseMethod: () => void;
  settings: () => void;
  /** Opens Translation for a review that belongs to the Guided workspace. */
  openGuided: (intent: GuidedIntent) => void;
}) {
  const project = state.project;
  if (!project)
    return <NoProject state={state} busy={busy} open={open} select={select} />;
  const available = !!project.available;
  return (
    <PageLayout variant="editor" className="project-page" aria-label="Project">
      <PageHeader
        title={project.name}
        description={
          <>
            {engineLabel(project.engine_label || project.engine)} ·{" "}
            {project.method ? methodLabels[project.method] : "No method chosen"}{" "}
            · <span title={project.source}>{project.source}</span>
          </>
        }
        actions={
          <div className="actions">
            {project.method && (
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
            { id: "versions", label: "Game updates", disabled: !available },
            { id: "backups", label: "Backups", disabled: !available },
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
        {tab === "versions" && (
          <ProjectVersions
            project={project}
            onBackups={() => onTab("backups")}
            openTask={openTask}
            openGuided={openGuided}
          />
        )}
        {tab === "backups" && <ProjectBackups />}
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
  openTask: (step: string, task: string) => void;
  openTranslation: () => void;
  chooseMethod: () => void;
  settings: () => void;
}) {
  const operation = project.operation;
  const active =
    !!operation && ["ready", "running", "waiting"].includes(operation.status);
  const guided = project.method === "guided" && progress;
  const primary = !project.available ? (
    <Button variant="primary" disabled={busy || state.running} onClick={open}>
      {project.next_label}
    </Button>
  ) : !project.method ? (
    <Button variant="primary" disabled={busy} onClick={chooseMethod}>
      Choose translation method
    </Button>
  ) : guided ? (
    <Button
      variant="primary"
      disabled={busy}
      onClick={() => openTask(progress.current.step, progress.current.task)}
    >
      Continue: {progress.current.title}
      <ArrowRight size={15} aria-hidden="true" />
    </Button>
  ) : (
    <Button variant="primary" disabled={busy} onClick={openTranslation}>
      Open {methodLabels[project.method]}
      <ArrowRight size={15} aria-hidden="true" />
    </Button>
  );
  return (
    <>
      <PageBody className="project-status">
        {active && <JobStatus job={operation} />}
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
                  : "Guided steps walk through each stage with estimates; Len's method hands the whole game to your coding assistant."
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
              >
                {progress.next &&
                  progress.next.task !== progress.current.task && (
                    <Button
                      disabled={busy}
                      onClick={() =>
                        openTask(progress.next!.step, progress.next!.task)
                      }
                    >
                      Go to {progress.next.title}
                    </Button>
                  )}
              </ActionRow>
            </ActionList>
            <Section title="Tasks" className="project-tasks-section">
              <ol className="project-stages">
                {progress.stages.map((stage, index) => (
                  <li key={stage.id}>
                    <h3>
                      <span
                        className="guided-stage-marker"
                        data-state={
                          stage.done === stage.total
                            ? "done"
                            : stage.done
                              ? "started"
                              : undefined
                        }
                        aria-hidden="true"
                      >
                        {stage.done === stage.total ? (
                          <Check size={12} strokeWidth={3} />
                        ) : (
                          index + 1
                        )}
                      </span>
                      {stage.short}
                      <span className="project-stage-count">
                        {stage.done}/{stage.total}
                      </span>
                    </h3>
                    <ul>
                      {stage.tasks.map((task) => (
                        <li key={task.id}>
                          <StatusIcon
                            status={task.done ? "done" : "idle"}
                            label={task.done ? "Complete" : "Not done"}
                            size={14}
                          />
                          <Button
                            variant="link"
                            disabled={busy}
                            aria-current={
                              task.id === progress.current.task
                                ? "step"
                                : undefined
                            }
                            onClick={() => openTask(stage.id, task.id)}
                          >
                            {task.title}
                          </Button>
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
                  <strong>{project.status}</strong>
                  {project.detail && <small>{project.detail}</small>}
                </>
              }
            />
          </ActionList>
        )}
        {!active && operation && (
          <p className="project-activity">
            Last activity: {operation.label} · {sentence(operation.status)}
          </p>
        )}
        {!state.provider_ready && (
          <Notice tone="warning">
            <span>Choose a connection and model before API translation.</span>
            <Button variant="link" disabled={busy} onClick={settings}>
              Open Settings
            </Button>
          </Notice>
        )}
      </PageBody>
      <ActionBar feedback={null}>{primary}</ActionBar>
    </>
  );
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
  const { snapshot } = useApplication();
  const guided = snapshot?.guided,
    translation = snapshot?.translation;
  const [footer, setFooter] = useState<HTMLDivElement | null>(null);
  const [inspection, setInspection] = useState<Job | null>(null);
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
  const backup = translation.lifecycle.source_backup;
  const baseline =
    !!backup && backup.available !== false && !!translation.git?.configured;
  return (
    <>
      <PageBody className="project-history-body">
        <ActivityHistory
          state={guided}
          translation={translation}
          inspect={setInspection}
          initialQuery={query}
          footerTarget={footer}
        />
      </PageBody>
      <ActionBar
        feedback={<div ref={setFooter} className="project-history-footer" />}
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
          reapply={async (job) =>
            openGuided({ kind: "reapply", runId: job.id })
          }
          actions={
            canResumeRun(inspected) && (
              <ActionList compact>
                <ActionRow
                  label={
                    <small>Continue Live with this run’s saved settings.</small>
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
          }
        />
      )}
    </>
  );
}

function ProjectVersions({
  project,
  onBackups,
  openTask,
  openGuided,
}: {
  project: Project;
  onBackups: () => void;
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
        <VersionsPanel
          guided={guided}
          project={project}
          state={translation}
          onBackups={onBackups}
          onPrepare={guided ? () => openTask("prepare", "baseline") : undefined}
          onCheckpoint={
            guided ? () => openGuided({ kind: "checkpoint" }) : undefined
          }
          actionTarget={target}
        />
      </PageBody>
      <ActionBar feedback={null}>
        <div ref={setTarget} className="action-bar-slot" />
      </ActionBar>
    </>
  );
}

function ProjectBackups() {
  const { snapshot } = useApplication();
  const translation = snapshot?.translation;
  const [target, setTarget] = useState<HTMLDivElement | null>(null);
  if (!translation) return null;
  return (
    <>
      <PageBody>
        <BackupsPanel state={translation} actionTarget={target} />
      </PageBody>
      <ActionBar feedback={null}>
        <div ref={setTarget} className="action-bar-slot" />
      </ActionBar>
    </>
  );
}

/** With no game open, the page offers to open one or a recent project. */
function NoProject({
  state,
  busy,
  open,
  select,
}: {
  state: AppState;
  busy: boolean;
  open: () => void;
  select: (id: string) => void;
}) {
  const recent = state.recent.slice(0, 5);
  return (
    <PageLayout className="project-page" aria-label="Project">
      <PageHeader title="Project" />
      <ActionList>
        <ActionRow
          title="No project open"
          description={`Open a game to get started${recent.length ? ", or choose a recent project below." : "."}`}
        >
          <Button variant="primary" disabled={busy} onClick={open}>
            <FolderOpen size={16} aria-hidden="true" />
            Open a game
          </Button>
        </ActionRow>
      </ActionList>
      {!!recent.length && (
        <Section title="Recent projects" className="project-recents">
          <div className="project-recent-list">
            {recent.map((item) => (
              <Button
                key={item.id}
                disabled={busy}
                onClick={() => select(item.id)}
              >
                <Folder size={17} aria-hidden="true" />
                <span>
                  <strong>{item.name}</strong>
                  <small title={item.source}>{item.source}</small>
                </span>
                <ArrowRight size={15} aria-hidden="true" />
              </Button>
            ))}
          </div>
        </Section>
      )}
    </PageLayout>
  );
}
