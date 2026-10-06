import { useEffect, useEffectEvent, useRef, useState } from "react";
import {
  House,
  Route,
  Settings2,
  FolderOpen,
  ChevronDown,
  ListChecks,
  Check,
} from "lucide-react";
import { api } from "../api/client";
import { flushDrafts } from "../state/leaveGuards";
import { useAction } from "../state/useAction";
import type { GuidedStep, Screen } from "../api/contracts";
import { useApplication } from "./ApplicationProvider";
import Overview from "../features/overview/Overview";
import Settings from "../features/settings/Settings";
import GuidedWorkflow from "../features/guided/GuidedWorkflow";
import { guidedProgress } from "../features/guided/progress";
import Translation from "../features/translation/Translation";
import { BackupsPanel } from "../features/translation/BackupsPanel";
import { VersionsPanel } from "../features/translation/VersionsPanel";
import { Menu, MenuItem, MenuSeparator } from "../ui/Menu";
import { Button } from "../ui/Button";
import { Message } from "../ui/Feedback";
import { DiagnosticsAction } from "./DiagnosticsAction";
import { ErrorBoundary } from "./ErrorBoundary";
import { TopbarSlot } from "./TopbarSlot";

export default function App() {
  const application = useApplication();
  const state = application.snapshot?.application;
  const action = useAction({ after: application.settle });
  const [topbarSlot, setTopbarSlot] = useState<HTMLElement | null>(null);
  // Settings stays mounted after its first visit so its session survives.
  const [settingsOpened, setSettingsOpened] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  if (state?.screen === "settings" && !settingsOpened) setSettingsOpened(true);
  const loaded = !!state;
  const reportReady = useEffectEvent((error: unknown) => action.report(error));
  const ready = useRef(false);
  useEffect(() => {
    if (!loaded || ready.current) return;
    ready.current = true;
    window.dazedtl.ready().catch(reportReady);
  }, [loaded]);
  const open = () =>
    action.run(async () => {
      const source = await window.dazedtl.chooseFolder();
      if (!source) return;
      await flushDrafts();
      await api.open(source);
      await application.settle();
      application.navigate("overview");
    });
  const select = (id: string) =>
    action.run(async () => {
      await flushDrafts();
      await api.select(id);
      await application.settle();
      application.navigate("overview");
    });
  const navigate = (screen: Screen) =>
    action.run(async () => {
      await flushDrafts();
      application.navigate(screen);
      // Linking a new Guided project is real setup work. Existing pages use
      // their observed data and do not send a navigation request to Python.
      if (
        ["guided", "manual"].includes(screen) &&
        !application.snapshot?.guided
      ) {
        await api.navigate(screen);
      }
    });
  // Overview reads Guided progress from the observed snapshot; no extra read.
  const guidedState = application.snapshot?.guided;
  const translationState = application.snapshot?.translation;
  const progress =
    state?.project &&
    guidedState?.projectId === state.project.id &&
    translationState?.projectId === state.project.id
      ? guidedProgress(guidedState, translationState)
      : null;
  const error = application.stopped
    ? application.error
    : action.error || application.error;
  const connection = application.stopped
    ? "App unavailable"
    : state
      ? "App ready"
      : "Starting…";
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span>D</span>DazedTL
        </div>
        {state?.project && (
          <Menu
            variant="quiet"
            className="current-project"
            title={state.project.name}
            label="Switch project"
            align="start"
            disabled={action.busy}
            trigger={
              <>
                <FolderOpen size={17} aria-hidden="true" />
                <span>{state.project.name}</span>
                <ChevronDown size={14} aria-hidden="true" />
              </>
            }
          >
            {state.recent.map((project) => (
              <MenuItem
                key={project.id}
                className="project-menu-item"
                current={project.id === state.project?.id}
                onSelect={() => {
                  if (project.id !== state.project?.id) void select(project.id);
                }}
              >
                <FolderOpen size={16} aria-hidden="true" />
                <span>
                  <strong>{project.name}</strong>
                  <small title={project.source}>{project.source}</small>
                </span>
                {project.id === state.project?.id && (
                  <Check size={15} aria-label="Open now" />
                )}
              </MenuItem>
            ))}
            <MenuSeparator />
            <MenuItem onSelect={() => void open()}>Open a game…</MenuItem>
          </Menu>
        )}
        <div className="topbar-actions" ref={setTopbarSlot} />
        <span className="connection" title={connection}>
          <i className={application.stopped ? "disconnected" : ""} />
          <span className="connection-label">{connection}</span>
        </span>
      </header>
      <TopbarSlot.Provider value={topbarSlot}>
        <div className="app-body">
          <aside className="sidebar">
            <nav aria-label="Main navigation">
              <Button
                aria-current={state?.screen === "overview" ? "page" : undefined}
                onClick={() => navigate("overview")}
              >
                <House size={18} />
                Overview
              </Button>
              {state?.project && (
                <>
                  <Button
                    aria-current={
                      ["guided", "manual"].includes(state.screen)
                        ? "page"
                        : undefined
                    }
                    disabled={
                      action.busy ||
                      !["MVMZ", "ACE"].includes(state.project.engine)
                    }
                    onClick={() => navigate("guided")}
                  >
                    <ListChecks size={18} />
                    Translation
                  </Button>
                  <Button
                    aria-current={
                      state.screen === "translation" ? "page" : undefined
                    }
                    onClick={() => navigate("translation")}
                  >
                    <Route size={18} />
                    Len's method
                  </Button>
                </>
              )}
            </nav>
            <div className="sidebar-bottom">
              <DiagnosticsAction />
              <Button
                aria-current={state?.screen === "settings" ? "page" : undefined}
                onClick={() => navigate("settings")}
              >
                <Settings2 size={18} />
                Settings
                {settingsDirty && state?.screen !== "settings" && (
                  <span
                    className="unsaved-dot"
                    role="img"
                    aria-label="Unsaved changes"
                  />
                )}
              </Button>
            </div>
          </aside>
          <main>
            <Message
              message={error}
              onDismiss={
                application.stopped
                  ? undefined
                  : () => {
                      action.clear();
                      application.clearError();
                    }
              }
            />
            {(settingsOpened || state?.screen === "settings") && (
              <div
                hidden={state?.screen !== "settings"}
                style={{ display: "contents" }}
              >
                <ErrorBoundary label="Settings">
                  <Settings onDirty={setSettingsDirty} />
                </ErrorBoundary>
              </div>
            )}
            <ErrorBoundary
              resetKey={`${state?.project?.id}:${state?.screen}`}
              label="This view"
            >
              {!state ? (
                <p className="muted">
                  {error
                    ? "Your workspace could not be opened."
                    : "Opening your workspace…"}
                </p>
              ) : state.screen === "overview" ? (
                <Overview
                  state={state}
                  busy={action.busy}
                  open={open}
                  select={select}
                  go={navigate}
                  report={action.report}
                  progress={progress}
                  openTask={(step, task) =>
                    void action.run(async () => {
                      await flushDrafts();
                      application.navigateGuided(state.project!.id, {
                        step: step as GuidedStep,
                        task,
                      });
                      application.navigate("guided");
                    })
                  }
                />
              ) : state.screen === "settings" ? null : state.project &&
                (state.screen === "guided" || state.screen === "manual") ? (
                <GuidedWorkflow
                  key={state.project.id}
                  project={state.project}
                  opening={action.busy}
                  settings={() => navigate("settings")}
                  backups={(target) =>
                    application.snapshot?.translation ? (
                      <BackupsPanel
                        state={application.snapshot.translation}
                        actionTarget={target}
                      />
                    ) : null
                  }
                  versions={(actions) =>
                    application.snapshot?.translation ? (
                      <VersionsPanel
                        guided
                        project={state.project!}
                        state={application.snapshot.translation}
                        onBackups={actions.backups}
                        onPrepare={actions.prepare}
                        onCheckpoint={actions.checkpoint}
                        actionTarget={actions.target}
                      />
                    ) : null
                  }
                />
              ) : state.project ? (
                <Translation
                  key={state.project.id}
                  project={state.project}
                  settings={() => navigate("settings")}
                  openGuided={
                    application.snapshot?.guided
                      ? () => navigate("guided")
                      : undefined
                  }
                />
              ) : null}
            </ErrorBoundary>
          </main>
        </div>
      </TopbarSlot.Provider>
    </div>
  );
}
