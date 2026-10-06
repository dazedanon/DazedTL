import { FolderOpen } from "lucide-react";
import type { GuidedState, TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { ErrorBoundary } from "../../app/ErrorBoundary";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { FeedbackOwners, useOwnedFeedback } from "../../ui/FeedbackOwners";
import { JobStatus } from "../../ui/JobStatus";
import { PageBody, PageHeader, PageLayout } from "../../ui/PageLayout";
import { Tabs } from "../../ui/Tabs";
import { ImageManager } from "../images/ImageManager";
import { ImageTextEditor } from "../images/ImageTextEditor";
import { WorkflowNavigation } from "./WorkflowNavigation";
import { runPhase, taskForStage } from "./workflow";
import { ActionReview } from "./workspace/ActionReview";
import { GuidedDialogs } from "./workspace/GuidedDialogs";
import { GuidedPanel } from "./workspace/GuidedPanel";
import { type GuidedProps, fileCount, phaseLabels } from "./workspace/model";
import { renderTask } from "./workspace/tasks";
import { useGuidedWorkspace } from "./workspace/useGuidedWorkspace";

export default function GuidedWorkflow(props: GuidedProps) {
  const { snapshot } = useApplication();
  const state = snapshot?.guided,
    translation = snapshot?.translation;
  if (
    !state ||
    state.projectId !== props.project.id ||
    !translation ||
    translation.projectId !== props.project.id
  )
    return props.opening && !snapshot?.translationError ? (
      <p className="muted" role="status">
        Opening translation workspace…
      </p>
    ) : (
      <Message
        message={
          snapshot?.translationError ||
          "Open this game’s Translation workspace to continue."
        }
      />
    );
  return (
    <FeedbackOwners key={props.project.id}>
      <Workspace {...props} state={state} translation={translation} />
    </FeedbackOwners>
  );
}

function Workspace(
  props: GuidedProps & { state: GuidedState; translation: TranslationState },
) {
  const w = useGuidedWorkspace(props);
  const {
    project,
    state,
    application,
    action,
    draft,
    stages,
    position,
    stage,
    selectedTask,
    taskId,
    taskView,
    taskIndex,
    showTaskTabs,
    taskTabsId,
    setPanel,
    imageView,
    setImageView,
    editorAssets,
    setEditorAssets,
    setPluginFooter,
    preview,
    setHistory,
    baselineNotice,
    bodyRef,
    headingRef,
    historyControl,
    preserved,
    baseline,
    changed,
    activeOperation,
    localOperation,
    backupPending,
    preparationPending,
    stopOperation,
    translationFlow,
    disabled,
    move,
    stepTask,
    task,
    textView,
    preparationComplete,
    completed,
  } = w;
  const owned = useOwnedFeedback(action.key);
  const { content, primary, secondary, actionContext } = renderTask(w);
  const previous =
    taskIndex > 0
      ? stage.tasks[taskIndex - 1]
      : stages[stages.indexOf(stage) - 1]?.tasks.at(-1);
  if (imageView && taskId === "images") {
    if (editorAssets)
      return (
        <ImageTextEditor
          projectId={project.id}
          assetIds={editorAssets}
          observationKey={application.snapshot}
          onClose={() => setEditorAssets(null)}
        />
      );
    return (
      <ImageManager
        projectId={project.id}
        initialMode={imageView}
        observed={application.snapshot?.images}
        onClose={() => setImageView(null)}
        onOpenEditor={(ids, mode) => {
          setImageView(mode || imageView);
          setEditorAssets(ids);
        }}
      />
    );
  }
  return (
    <PageLayout
      variant="editor"
      className={`guided-workspace${["context", "plugins"].includes(position.step) ? " guided-workspace--bounded" : ""}`}
      aria-label="Translation workspace"
    >
      <PageHeader
        className="guided-header"
        title="Translation"
        description={
          state.engine === "ACE" ? "RPG Maker VX Ace" : "RPG Maker MV / MZ"
        }
        actions={
          <div className="actions">
            <Button variant="quiet" onClick={() => setPanel("project-tools")}>
              Project tools
            </Button>
            <Button
              ref={historyControl}
              variant="quiet"
              onClick={() => setHistory("all")}
            >
              History
            </Button>
            <Button
              variant="quiet"
              onClick={() =>
                action.run(
                  () => window.dazedtl.openFolder("project"),
                  "Game folder opened.",
                  "open-game",
                )
              }
            >
              <FolderOpen size={16} />
              Game folder
            </Button>
          </div>
        }
      />
      <div className="guided-layout">
        <WorkflowNavigation
          stages={stages}
          step={position.step}
          completed={completed}
          disabled={disabled}
          move={move}
          taskFor={(stage) => taskForStage(state, stage)}
        />
        <div className="guided-task-workspace">
          {showTaskTabs && (
            <nav
              className="guided-task-nav"
              aria-label={`${stage.title} tasks`}
            >
              <Tabs
                id={taskTabsId}
                label={`${stage.title} tasks`}
                value={taskId}
                disabled={disabled}
                onChange={stepTask}
                items={stage.tasks.map((item) => ({
                  id: item.id,
                  label: (
                    <>
                      {completed.has(item.id) && (
                        <span aria-label="Complete">✓</span>
                      )}
                      {item.title}
                    </>
                  ),
                }))}
              />
            </nav>
          )}
          {activeOperation &&
            !localOperation &&
            !(
              position.step === "translate" &&
              activeOperation.action === "refresh_sources"
            ) &&
            !(
              taskId === "names" && activeOperation.action === "speaker_scan"
            ) && (
              <div className="guided-operation">
                <JobStatus
                  compact
                  job={{
                    ...activeOperation,
                    label: activeOperation.label || "Current operation",
                  }}
                />
                <Button
                  disabled={action.busy}
                  onClick={() => stopOperation(activeOperation)}
                >
                  Stop operation
                </Button>
              </div>
            )}
          <PageBody
            ref={bodyRef}
            role={showTaskTabs && selectedTask ? "tabpanel" : undefined}
            id={
              showTaskTabs && selectedTask
                ? `${taskTabsId}-panel-${taskId}`
                : undefined
            }
            aria-labelledby={
              showTaskTabs && selectedTask
                ? `${taskTabsId}-tab-${taskId}`
                : undefined
            }
            className={`guided-task-body${position.step === "translate" ? " translation-task-body" : position.step === "context" ? " context-task-body" : ""}${taskId === "plugins" ? " plugin-task-body" : taskId === "guidance" ? " context-guidance-body" : ""}`}
          >
            {position.step !== "translate" &&
              (position.step !== "context" || taskId === "run") && (
                <div className="guided-task-heading">
                  <div className="guided-task-location">
                    <span>
                      {stage.title}
                      {taskId === "plugins"
                        ? ""
                        : taskIndex >= 0
                          ? ` · Task ${taskIndex + 1} of ${stage.tasks.length}`
                          : " · Saved run"}
                    </span>
                    <Button variant="quiet" onClick={() => setPanel("tasks")}>
                      All tasks
                    </Button>
                  </div>
                  <h2 ref={headingRef} tabIndex={-1}>
                    {taskId === "apply" && taskView === "qa"
                      ? "Text QA · optional"
                      : taskId === "apply" && taskView === "tools"
                        ? "Game tools · optional"
                        : selectedTask?.title ||
                          phaseLabels[runPhase(state)] + " run"}
                  </h2>
                  {selectedTask?.description && (
                    <p>{selectedTask.description}</p>
                  )}
                  {taskId === "other-event-text" && (
                    <p className="muted">
                      {
                        {
                          audit: "Investigation",
                          sources: "Findings & source choices",
                          "advanced-run": "Translation",
                          variables: "Comparison updates",
                        }[state.eventText.view]
                      }
                    </p>
                  )}
                </div>
              )}
            <Message
              message={
                !preview &&
                !translationFlow.active &&
                !owned &&
                !action.key.startsWith("run:retain:") &&
                !(taskId === "run" && action.key.startsWith("run:"))
                  ? action.error
                  : ""
              }
              onDismiss={action.clear}
            />
            <Message message={state.collectionError} />
            {changed.length > 0 &&
              ["translate", "advanced", "apply", "review"].includes(
                position.step,
              ) && (
                <div className="guided-source-alert">
                  <p>
                    {fileCount(changed.length)} have changed sources. Resync the
                    affected working files before new work.
                  </p>
                  {position.step !== "translate" &&
                    task(
                      "refresh_sources",
                      "Resync",
                      {},
                      !preserved || !!activeOperation,
                      "default",
                      changed,
                    )}
                </div>
              )}
            {baselineNotice && taskId === "names" && (
              <p className="guided-success" role="status">
                {baselineNotice}
              </p>
            )}
            {taskId === "apply" && (
              <div className="text-workspace-nav">
                <div role="group" aria-label="Apply and Fitting views">
                  {(["apply", "fitting"] as const).map((view) => (
                    <Button
                      key={view}
                      aria-pressed={taskView === view}
                      disabled={disabled}
                      onClick={() => textView(view)}
                    >
                      {view === "apply" ? "Apply" : "Fitting"}
                    </Button>
                  ))}
                </div>
                <div className="actions">
                  <Button
                    variant="quiet"
                    aria-pressed={taskView === "qa"}
                    disabled={disabled}
                    onClick={() => textView("qa")}
                  >
                    Text QA · optional
                  </Button>
                  {state.engine === "MVMZ" && (
                    <Button
                      variant="quiet"
                      aria-pressed={taskView === "tools"}
                      disabled={disabled}
                      onClick={() => textView("tools")}
                    >
                      Tools · optional
                    </Button>
                  )}
                </div>
              </div>
            )}
            {taskId === "other-event-text" && (
              <div
                className="translation-substeps"
                role="group"
                aria-label="Event text steps"
              >
                {(
                  [
                    "audit",
                    "sources",
                    "advanced-run",
                    ...(state.comparisons.status !== "not_needed"
                      ? ["variables"]
                      : []),
                  ] as string[]
                ).map((view) => (
                  <Button
                    key={view}
                    variant="quiet"
                    aria-pressed={taskView === view}
                    disabled={disabled}
                    onClick={() => stepTask(view)}
                  >
                    {
                      {
                        audit: "Investigate",
                        sources: "Source choices",
                        "advanced-run": "Translate",
                        variables: "Update comparisons",
                      }[view]
                    }
                  </Button>
                ))}
              </div>
            )}
            <ErrorBoundary resetKey={`${taskId}:${taskView}`} label="This task">
              {content}
            </ErrorBoundary>
          </PageBody>
          {taskId === "plugins" ? (
            <div className="plugin-host-footer" ref={setPluginFooter} />
          ) : (
            <ActionBar
              feedback={
                actionContext || (
                  <div className="guided-footer-context">
                    {previous && (
                      <Button
                        variant="quiet"
                        disabled={action.busy}
                        onClick={() => stepTask(previous.id)}
                      >
                        Back
                      </Button>
                    )}
                    {position.step !== "context" && (
                      <span
                        className={
                          backupPending || preparationPending
                            ? "guided-prepare-feedback"
                            : undefined
                        }
                      >
                        {backupPending
                          ? "Backup in progress"
                          : preparationPending
                            ? "Preparation in progress"
                            : taskId === "format" &&
                                (preparationComplete || baseline)
                              ? "Game files prepared"
                              : draft.dirty
                                ? "Options retained for recovery"
                                : preserved
                                  ? "Original preserved"
                                  : "Start by preserving the original"}
                      </span>
                    )}
                  </div>
                )
              }
            >
              {secondary}
              {primary}
            </ActionBar>
          )}
        </div>
      </div>
      <GuidedPanel w={w} />
      <GuidedDialogs w={w} />
      <ActionReview w={w} />
    </PageLayout>
  );
}
