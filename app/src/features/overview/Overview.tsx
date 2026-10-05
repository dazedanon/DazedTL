import { DetailRow } from "../../ui/FieldRow";
import { PageLayout, PageHeader } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { Button } from "../../ui/Button";
import { JobStatus } from "../../ui/JobStatus";
import {
  ArrowRight,
  Folder,
  FolderOpen,
  Settings2,
} from "lucide-react";
import type { AppState, Screen } from "../../api/contracts";

const engines: Record<string, string> = {
  MVMZ: "RPG Maker MV / MZ",
  ACE: "RPG Maker VX Ace",
  WOLF: "WOLF RPG",
};

export default function Overview({
  state,
  busy,
  open,
  select,
  go,
  report,
}: {
  state: AppState;
  busy: boolean;
  open: () => void;
  select: (id: string) => void;
  go: (screen: Screen) => void;
  report: (error: unknown) => void;
}) {
  const project = state.project;
  const recent = state.recent
    .filter((item) => item.id !== project?.id)
    .slice(0, 3);
  const switchingDisabled = busy;
  return (
    <PageLayout className="overview" aria-label="Project overview">
      <PageHeader title="Overview" divided />
      <Section title="Current project" id="overview-current">
        {project ? (
          <>
            <h3 className="overview-project-name">{project.name}</h3>
            <dl className="overview-facts">
              <DetailRow label="Engine">
                {project.engine_label ||
                  engines[project.engine] ||
                  project.engine}
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
                    {project.operation ? (
                      <JobStatus job={project.operation} />
                    ) : (
                      <>
                        <strong role="status">{project.status}</strong>
                        {project.detail && <p>{project.detail}</p>}
                      </>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="primary"
                    disabled={busy || (!project.available && state.running)}
                    onClick={() =>
                      project.available ? go(["MVMZ", "ACE"].includes(project.engine) ? "guided" : "translation") : open()
                    }
                  >
                    {project.available && ["MVMZ", "ACE"].includes(project.engine) ? "Open Translation" : project.next_label}
                    <ArrowRight size={15} />
                  </Button>
                </dd>
              </div>
            </dl>
            {project.available && ["MVMZ", "ACE"].includes(project.engine) && <div className="actions overview-workflow-actions">
              <Button disabled={busy} onClick={() => go("translation")}>Open Len's method</Button>
            </div>}
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
      <Section title="Quickstart" id="overview-quickstart">
        <div className="overview-actions">
          {project && (
            <Button type="button" disabled={switchingDisabled} onClick={open}>
              <FolderOpen size={15} />
              Open another game
            </Button>
          )}
          <Button type="button" disabled={busy} onClick={() => go("settings")}>
            <Settings2 size={15} />
            Translation settings
          </Button>
          {!state.provider_ready && (
            <span className="overview-setup-note">
              Choose a connection and model for live or batch translation.
            </span>
          )}
        </div>
      </Section>
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
