import { useEffect, useEffectEvent, useRef, useState } from "react";
import {
  House,
  Route,
  Settings2,
  FolderOpen,
  ChevronDown,
  X,
  ListChecks,
} from "lucide-react";
import { api } from "../api/client";
import { flushDrafts } from "../state/leaveGuards";
import { useAction } from "../state/useAction";
import type { Screen } from "../api/contracts";
import { useApplication } from "./ApplicationProvider";
import Overview from "../features/overview/Overview";
import Settings from "../features/settings/Settings";
import GuidedWorkflow from "../features/guided/GuidedWorkflow";
import Translation from "../features/translation/Translation";
import { BackupsPanel } from "../features/translation/BackupsPanel";
import { VersionsPanel } from "../features/translation/VersionsPanel";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { Message } from "../ui/Feedback";
import { DiagnosticsAction } from "./DiagnosticsAction";
import { ErrorBoundary } from "./ErrorBoundary";
import { TopbarSlot } from "./TopbarSlot";

export default function App() {
  const application = useApplication();
  const state = application.snapshot?.application;
  const action = useAction({ after: application.settle });
  const [picker, setPicker] = useState(false);
  const [topbarSlot, setTopbarSlot] = useState<HTMLElement | null>(null);
  // Settings stays mounted after its first visit so its session survives.
  const [settingsOpened, setSettingsOpened] = useState(false);
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
      setPicker(false);
    });
  const select = (id: string) =>
    action.run(async () => {
      await flushDrafts();
      await api.select(id);
      await application.settle();
      application.navigate("overview");
      setPicker(false);
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
  const error = application.stopped
    ? application.error
    : action.error || application.error;
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span>D</span>DazedTL
        </div>
        {state?.project && (
          <Button
            size="comfortable"
            variant="quiet"
            className="current-project"
            title={state.project.name}
            onClick={() => setPicker(true)}
            disabled={action.busy}
          >
            <FolderOpen size={17} />
            <span>{state.project.name}</span>
            <ChevronDown size={14} />
          </Button>
        )}
        <div className="topbar-actions" ref={setTopbarSlot} />
        <span className="connection">
          <i className={application.stopped ? "disconnected" : ""} />
          {application.stopped
            ? "App unavailable"
            : state
              ? "App ready"
              : "Starting…"}
        </span>
      </header>
      <TopbarSlot.Provider value={topbarSlot}>
        <div className="app-body">
          <aside className="sidebar">
            <nav aria-label="Main navigation">
              <Button
                size="comfortable"
                aria-current={state?.screen === "overview" ? "page" : undefined}
                onClick={() => navigate("overview")}
              >
                <House size={18} />
                Overview
              </Button>
              {state?.project && (
                <>
                  <Button
                    size="comfortable"
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
                    size="comfortable"
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
                size="comfortable"
                aria-current={state?.screen === "settings" ? "page" : undefined}
                onClick={() => navigate("settings")}
              >
                <Settings2 size={18} />
                Settings
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
                  <Settings />
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
                  legacy={
                    application.snapshot?.guided ? (
                      <Button
                        variant="primary"
                        onClick={() => navigate("guided")}
                      >
                        Open Translation and saved runs
                      </Button>
                    ) : null
                  }
                />
              ) : null}
            </ErrorBoundary>
          </main>
        </div>
      </TopbarSlot.Provider>
      {picker && (
        <Modal
          label="Switch project"
          onDismiss={() => setPicker(false)}
          dismissible={!action.busy}
        >
          <div className="section-heading">
            <h2>Switch project</h2>
            <Button
              size="comfortable"
              variant="quiet"
              aria-label="Close project picker"
              onClick={() => setPicker(false)}
            >
              <X size={17} />
            </Button>
          </div>
          <div className="recents">
            {state?.recent.map((project) => (
              <Button
                size="comfortable"
                key={project.id}
                disabled={action.busy}
                onClick={() => select(project.id)}
              >
                <FolderOpen size={18} />
                <span>
                  <strong>{project.name}</strong>
                  <small>{project.source}</small>
                </span>
              </Button>
            ))}
          </div>
          <Button
            size="comfortable"
            variant="primary"
            disabled={action.busy}
            onClick={open}
          >
            Open a game
          </Button>
        </Modal>
      )}
    </div>
  );
}
