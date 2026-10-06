import { DetailRow } from "../../ui/FieldRow";
import { PageLayout, PageHeader } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { Button } from "../../ui/Button";
import { JobStatus } from "../../ui/JobStatus";
import { Notice } from "../../ui/Notice";
import { engineLabel } from "../../ui/displayText";
import { ArrowRight, Folder, FolderOpen } from "lucide-react";
import type { AppState, Screen } from "../../api/contracts";
import { StatusIcon } from "../../ui/StatusIcon";

const sentence = (value: string) =>
  value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ");

/** Where a Guided project stands, as the shell reads it from saved state. */
type Progress = {
  stages: { id: string; short: string; done: number; total: number }[];
  next: {
    step: string;
    stage: string;
    task: string;
    title: string;
    description: string;
  } | null;
  current: { step: string; task: string; stage: string; title: string };
};

export default function Overview({
  state,
  busy,
  open,
  select,
  go,
  report,
  progress,
  openTask,
}: {
  state: AppState;
  busy: boolean;
  open: () => void;
  select: (id: string) => void;
  go: (screen: Screen) => void;
  report: (error: unknown) => void;
  progress?: Progress | null;
  openTask: (step: string, task: string) => void;
}) {
  const project = state.project;
  const recent = state.recent
    .filter((item) => item.id !== project?.id)
    .slice(0, 3);
  const switchingDisabled = busy;
  const operation = project?.operation;
  const active =
    !!operation && ["ready", "running", "waiting"].includes(operation.status);
  const guided = !!project && ["MVMZ", "ACE"].includes(project.engine);
  return (
    <PageLayout className="overview" aria-label="Project overview">
      <PageHeader title="Overview" divided />
      <Section title="Current project" id="overview-current">
        {project ? (
          <>
            <h3 className="overview-project-name">{project.name}</h3>
            <dl className="overview-facts">
              <DetailRow label="Engine">
                {engineLabel(project.engine_label || project.engine)}
              </DetailRow>
              <div className="summary-row overview-wide">
                <dt>Folder</dt>
                <dd className="overview-folder">
                  <span title={project.source}>{project.source}</span>
                  <Button
                    type="button"
                    variant="quiet"
                    disabled={!project.available}
                    onClick={() =>
                      window.dazedtl.openFolder("project").catch(report)
                    }
                  >
                    <FolderOpen size={14} />
                    Open folder
                  </Button>
                </dd>
              </div>
              <div className="summary-row overview-wide overview-status">
                <dt>Status</dt>
                <dd>
                  <div className="overview-status-copy">
                    {active ? (
                      <JobStatus job={operation} />
                    ) : progress ? (
                      progress.next ? (
                        <>
                          <strong role="status">
                            Next: {progress.next.stage} · {progress.next.title}
                          </strong>
                          <p>{progress.next.description}</p>
                        </>
                      ) : (
                        <>
                          <strong role="status">Required tasks are done</strong>
                          <p>Build a release when the translation is ready.</p>
                        </>
                      )
                    ) : (
                      <>
                        <strong role="status">{project.status}</strong>
                        {project.detail && <p>{project.detail}</p>}
                      </>
                    )}
                  </div>
                </dd>
              </div>
              {progress && (
                <div className="summary-row overview-wide">
                  <dt>Stages</dt>
                  <dd>
                    <ol className="overview-stages">
                      {progress.stages.map((stage) => (
                        <li key={stage.id}>
                          {stage.short}
                          {stage.done === stage.total ? (
                            <StatusIcon
                              status="done"
                              label="Tasks completed"
                              size={14}
                            />
                          ) : stage.done ? (
                            <span className="overview-stage-count">
                              {stage.done}/{stage.total}
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ol>
                  </dd>
                </div>
              )}
              {!active && operation && progress && (
                <DetailRow label="Last activity">
                  <span className="overview-activity">
                    {operation.label} · {sentence(operation.status)}
                  </span>
                </DetailRow>
              )}
            </dl>
            <div className="actions overview-workflow-actions">
              <Button
                type="button"
                variant="primary"
                disabled={busy || (!project.available && state.running)}
                onClick={() =>
                  !project.available
                    ? open()
                    : progress
                      ? openTask(progress.current.step, progress.current.task)
                      : go(guided ? "guided" : "translation")
                }
              >
                {!project.available
                  ? project.next_label
                  : progress
                    ? `Continue: ${progress.current.title}`
                    : guided
                      ? "Open Translation"
                      : project.next_label}
                <ArrowRight size={15} />
              </Button>
              {progress?.next &&
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
              {project.available && guided && (
                <Button disabled={busy} onClick={() => go("translation")}>
                  Open Len&apos;s method
                </Button>
              )}
            </div>
          </>
        ) : (
          <div className="overview-empty">
            <div>
              <h3>
                <Folder size={18} />
                No project open
              </h3>
              <p>
                Open a game to get started
                {recent.length ? ", or choose a recent project below." : "."}
              </p>
            </div>
            <Button
              type="button"
              variant="primary"
              disabled={switchingDisabled}
              onClick={open}
            >
              <FolderOpen size={16} />
              Open a game
            </Button>
          </div>
        )}
      </Section>
      {!state.provider_ready && (
        <Notice tone="warning">
          <span>Choose a connection and model before API translation.</span>
          <Button variant="link" disabled={busy} onClick={() => go("settings")}>
            Open Settings
          </Button>
        </Notice>
      )}
      {!!recent.length && (
        <Section
          title="Recent projects"
          className="overview-recents"
          id="overview-recent"
        >
          <div className="overview-recent-list">
            {recent.map((item) => (
              <Button
                type="button"
                key={item.id}
                disabled={switchingDisabled}
                onClick={() => select(item.id)}
              >
                <Folder size={17} />
                <span>
                  <strong>{item.name}</strong>
                  <small title={item.source}>{item.source}</small>
                </span>
                <ArrowRight size={15} />
              </Button>
            ))}
          </div>
        </Section>
      )}
    </PageLayout>
  );
}
