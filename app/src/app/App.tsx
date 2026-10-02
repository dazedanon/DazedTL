import { useEffect, useRef, useState } from "react";
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

export default function App() {
  const application = useApplication();
  const state = application.snapshot?.application;
  const action = useAction({ after: application.refresh });
  const [picker, setPicker] = useState(false);
  const ready = useRef(false);
  useEffect(() => {
    if (state && !ready.current) {
      ready.current = true;
      window.dazedtl.ready().catch(action.report);
    }
  }, [!!state]);
  const open = () =>
    action.run(async () => {
      const source = await window.dazedtl.chooseFolder();
      if (!source) return;
      await flushDrafts();
      await api.open(source);
      setPicker(false);
    });
  const select = (id: string) =>
    action.run(async () => {
      await flushDrafts();
      await api.select(id);
      setPicker(false);
    });
  const navigate = (screen: Screen) =>
    action.run(async () => {
      await flushDrafts();
      await api.navigate(screen);
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
        <span className="connection">
          <i className={application.stopped ? "disconnected" : ""} />
          {application.stopped
            ? "App unavailable"
            : state
              ? "App ready"
              : "Starting…"}
        </span>
      </header>
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
            {state?.project && <>
              <Button size="comfortable" aria-current={["guided", "manual"].includes(state.screen) ? "page" : undefined}
                disabled={action.busy || !["MVMZ", "ACE"].includes(state.project.engine)} onClick={() => navigate("guided")}>
                <ListChecks size={18} />Translation
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
            </>}
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
        <main
          className={
            state?.screen === "guided" || state?.screen === "manual"
              ? "editor-main guided-main"
              : state?.screen === "settings"
              ? "editor-main"
              : state?.screen === "overview"
                ? "overview-main"
                : undefined
          }
        >
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
          ) : state.screen === "settings" ? (
            <Settings />
          ) : state.project && (state.screen === "guided" || state.screen === "manual") ? (
            <GuidedWorkflow key={state.project.id} project={state.project} settings={() => navigate("settings")}
              backups={application.snapshot?.translation ? <BackupsPanel state={application.snapshot.translation} /> : null}
              versions={application.snapshot?.translation ? <VersionsPanel guided project={state.project} state={application.snapshot.translation} /> : null} />
          ) : state.project ? (
            <Translation
              key={state.project.id}
              project={state.project}
              settings={() => navigate("settings")}
              legacy={
                application.snapshot?.guided ? (
                  <Button variant="primary" onClick={() => navigate("guided")}>Open Translation and saved runs</Button>
                ) : null
              }
            />
          ) : null}
        </main>
      </div>
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
