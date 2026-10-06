import { useEffect, useEffectEvent, useRef, useState } from "react";
import {
  Gamepad2,
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
import type { GuidedStep, Screen, TranslationMethod } from "../api/contracts";
import { useApplication } from "./ApplicationProvider";
import Settings from "../features/settings/Settings";
import GuidedWorkflow from "../features/guided/GuidedWorkflow";
import { guidedProgress, projectAmounts } from "../features/guided/progress";
import type { GuidedIntent } from "../features/guided/workspace/model";
import ProjectPage, { type ProjectTab } from "../features/project/ProjectPage";
import { MethodDialog } from "../features/project/MethodDialog";
import Translation from "../features/translation/Translation";
import { Menu, MenuItem, MenuSeparator } from "../ui/Menu";
import { Button } from "../ui/Button";
import { Message } from "../ui/Feedback";
import { DiagnosticsAction } from "./DiagnosticsAction";
import { ErrorBoundary } from "./ErrorBoundary";

const workspaces: readonly Screen[] = ["guided", "manual", "translation"];

export default function App() {
  const application = useApplication();
  const state = application.snapshot?.application;
  const action = useAction({ after: application.settle });
  // Settings stays mounted after its first visit so its session survives.
  const [settingsOpened, setSettingsOpened] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  if (state?.screen === "settings" && !settingsOpened) setSettingsOpened(true);
  const [projectTab, setProjectTab] = useState<ProjectTab>("status");
  const [historyQuery, setHistoryQuery] = useState<string>();
  const [methodOpen, setMethodOpen] = useState(false);
  // A newly opened game asks for its method once it is observed.
  const [askMethod, setAskMethod] = useState(false);
  const [intent, setIntent] = useState<GuidedIntent | null>(null);
  const project = state?.project;
  // Project tabs and requests belong to one game; switching starts fresh.
  const [owner, setOwner] = useState(project?.id);
  if (owner !== project?.id) {
    setOwner(project?.id);
    setProjectTab("status");
    setHistoryQuery(undefined);
    setIntent(null);
    setMethodOpen(false);
  }
  if (askMethod && project) {
    setAskMethod(false);
    if (!project.method && project.available) setMethodOpen(true);
  }
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
      application.navigate("project");
      setAskMethod(true);
    });
  const select = (id: string) =>
    action.run(async () => {
      await flushDrafts();
      await api.select(id);
      await application.settle();
      application.navigate("project");
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
  // The one Translation entry opens the method the game uses, or asks.
  const openTranslation = () => {
    if (!project?.method) setMethodOpen(true);
    else void navigate(project.method === "guided" ? "guided" : "translation");
  };
  const chooseMethod = (method: TranslationMethod) =>
    void action.run(async () => {
      await flushDrafts();
      await api.method(project!.id, method);
      await application.settle();
      setMethodOpen(false);
      application.navigate(method === "guided" ? "guided" : "translation");
    });
  const openProject = (tab: Exclude<ProjectTab, "status">, query?: string) =>
    void action.run(async () => {
      await flushDrafts();
      setProjectTab(tab);
      setHistoryQuery(query);
      application.navigate("project");
    });
  const openTask = (step: string, task: string) =>
    void action.run(async () => {
      await flushDrafts();
      application.navigateGuided(project!.id, {
        step: step as GuidedStep,
        task,
      });
      application.navigate("guided");
    });
  const openGuided = (request: GuidedIntent) =>
    void action.run(async () => {
      await flushDrafts();
      application.navigate("guided");
      setIntent(request);
    });
  // The Project page reads Guided progress from the observed snapshot.
  const guidedState = application.snapshot?.guided;
  const translationState = application.snapshot?.translation;
  const progress =
    project &&
    guidedState?.projectId === project.id &&
    translationState?.projectId === project.id
      ? guidedProgress(guidedState, translationState)
      : null;
  const amounts = progress && guidedState ? projectAmounts(guidedState) : null;
  const error = application.stopped
    ? application.error
    : action.error || application.error;
  const connection = application.stopped
    ? "App unavailable"
    : state
      ? "App ready"
      : "Starting…";
  const workspace = !!state && workspaces.includes(state.screen);
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span>D</span>DazedTL
        </div>
        {project && (
          <Menu
            variant="quiet"
            className="current-project"
            title={project.name}
            label="Switch project"
            align="start"
            disabled={action.busy}
            trigger={
              <>
                <FolderOpen size={17} aria-hidden="true" />
                <span>{project.name}</span>
                <ChevronDown size={14} aria-hidden="true" />
              </>
            }
          >
            {state.recent.map((item) => (
              <MenuItem
                key={item.id}
                className="project-menu-item"
                current={item.id === project.id}
                onSelect={() => {
                  if (item.id !== project.id) void select(item.id);
                }}
              >
                <FolderOpen size={16} aria-hidden="true" />
                <span>
                  <strong>{item.name}</strong>
                  <small title={item.source}>{item.source}</small>
                </span>
                {item.id === project.id && (
                  <Check size={15} aria-label="Open now" />
                )}
              </MenuItem>
            ))}
            <MenuSeparator />
            <MenuItem onSelect={() => void open()}>Open a game…</MenuItem>
          </Menu>
        )}
        <span className="connection" title={connection}>
          <i className={application.stopped ? "disconnected" : ""} />
          <span className="connection-label">{connection}</span>
        </span>
      </header>
      <div className="app-body">
        <aside className="sidebar">
          <nav aria-label="Main navigation">
            <Button
              aria-current={state?.screen === "project" ? "page" : undefined}
              onClick={() => navigate("project")}
            >
              <Gamepad2 size={18} />
              Project
            </Button>
            {project && (
              <Button
                aria-current={workspace ? "page" : undefined}
                disabled={action.busy || !project.available}
                onClick={openTranslation}
              >
                {project.method === "len" ? (
                  <Route size={18} />
                ) : (
                  <ListChecks size={18} />
                )}
                Translation
              </Button>
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
            resetKey={`${project?.id}:${state?.screen}`}
            label="This view"
          >
            {!state ? (
              <p className="muted">
                {error
                  ? "Your workspace could not be opened."
                  : "Opening your workspace…"}
              </p>
            ) : state.screen === "settings" ? null : workspace &&
              project?.method === "guided" ? (
              <GuidedWorkflow
                key={project.id}
                project={project}
                opening={action.busy}
                settings={() => navigate("settings")}
                openProject={openProject}
                intent={intent}
                intentHandled={() => setIntent(null)}
              />
            ) : workspace && project?.method === "len" ? (
              <Translation
                key={project.id}
                project={project}
                settings={() => navigate("settings")}
                openProject={openProject}
              />
            ) : (
              <ProjectPage
                state={state}
                busy={action.busy}
                open={open}
                select={select}
                report={action.report}
                progress={progress}
                amounts={amounts}
                tab={projectTab}
                onTab={(tab) =>
                  void action.run(async () => {
                    await flushDrafts();
                    setProjectTab(tab);
                    setHistoryQuery(undefined);
                  })
                }
                historyQuery={historyQuery}
                openTask={openTask}
                openTranslation={openTranslation}
                chooseMethod={() => setMethodOpen(true)}
                settings={() => navigate("settings")}
                openGuided={openGuided}
              />
            )}
          </ErrorBoundary>
        </main>
      </div>
      {methodOpen && project && (
        <MethodDialog
          key={project.id}
          project={project}
          busy={action.busy}
          choose={chooseMethod}
          close={() => setMethodOpen(false)}
        />
      )}
    </div>
  );
}
