import { useRef } from "react";
import type { GuidedState, TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { ErrorBoundary } from "../../app/ErrorBoundary";
import { saveKey, taskKey, useShortcut } from "../../state/useShortcut";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Notice } from "../../ui/Notice";
import { FeedbackOwners, useOwnedFeedback } from "../../ui/FeedbackOwners";
import { JobStatus } from "../../ui/JobStatus";
import { PageBody, PageLayout } from "../../ui/PageLayout";
import { StatusIcon } from "../../ui/StatusIcon";
import { Tabs } from "../../ui/Tabs";
import { displayLabels, displayMarks } from "../../ui/displayStatus";
import { ImageTextEditor } from "../images/ImageTextEditor";
import { WorkflowNavigation } from "./WorkflowNavigation";
import { runPhase, taskForStage } from "./workflow";
import { ActionReview } from "./workspace/ActionReview";
import { PendingReview } from "./workspace/PendingReview";
import { GuidedDialogs } from "./workspace/GuidedDialogs";
import { GuidedPanel } from "./workspace/GuidedPanel";
import { type GuidedProps, fileCount, phaseLabels } from "./workspace/model";
import { renderTask } from "./workspace/tasks";
import { TaskHeader } from "./workspace/TaskHeader";
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
    showTaskTabs,
    taskTabsId,
    editorAssets,
    setEditorAssets,
    setTaskFooter,
    preview,
    setupNotice,
    bodyRef,
    headingRef,
    preserved,
    changed,
    activeOperation,
    localOperation,
    stopOperation,
    translationFlow,
    disabled,
    move,
    stepTask,
    back,
    previous,
    next,
    task,
    setPanel,
    completed,
    needsReview,
  } = w;
  const owned = useOwnedFeedback(action.key);
  const {
    content,
    secondary,
    action: taskAction,
    next: taskNext,
    actionContext,
    heading,
    save,
  } = renderTask(w);
  // Keys only save the open task or move between tasks; they never submit work.
  const frame = useRef<HTMLElement>(null);
  const step = (target: ReturnType<typeof previous>) =>
    target && !action.busy && !draft.committing
      ? () => stepTask(target.id)
      : undefined;
  useShortcut(saveKey, save, frame, { inFields: true });
  useShortcut(taskKey("back"), step(previous()), frame);
  useShortcut(taskKey("next"), step(next()), frame);
  // Views inside one task share the secondary tabs below the task tabs.
  const viewTabs =
    taskId === "other-event-text"
      ? [
          { id: "audit", label: "Investigate" },
          { id: "sources", label: "Source choices" },
          { id: "advanced-run", label: "Translate" },
          ...(state.comparisons.status !== "not_needed"
            ? [{ id: "variables", label: "Update comparisons" }]
            : []),
        ]
      : null;
  // The footer reports only this task's own state; a running backup or
  // preparation already shows its progress and pending button in the task.
  const status =
    position.step !== "context" && draft.dirty
      ? "Option changes take effect on the next run"
      : "";
  // Plugin files and Images bring their own action bar for the shared footer.
  const hostedFooter = taskId === "plugins" || taskId === "images";
  const textTranslation = position.step === "translate" && !hostedFooter;
  return (
    <PageLayout
      ref={frame}
      variant="editor"
      wide={taskId === "images"}
      className="guided-workspace"
      aria-label="Translation workspace"
    >
      <h1 className="sr-only">Translation</h1>
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
              className="guided-task-nav frame-row"
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
                  label:
                    item.optional &&
                    !completed.has(item.id) &&
                    !needsReview.has(item.id) ? (
                      <>
                        {item.title}
                        <span className="ui-tab-hint">optional</span>
                      </>
                    ) : (
                      item.title
                    ),
                  // A choice still waiting shows before an earlier completion.
                  status: needsReview.has(item.id) ? (
                    <StatusIcon
                      status={displayMarks.needs_review}
                      label={displayLabels.needs_review}
                      size={14}
                    />
                  ) : (
                    completed.has(item.id) && (
                      <StatusIcon status="done" label="Complete" size={14} />
                    )
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
              <div className="guided-operation frame-row">
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
            className={`guided-task-body${textTranslation ? " translation-task-body" : position.step === "context" ? " context-task-body" : ""}${taskId === "plugins" ? " plugin-task-body" : taskId === "images" ? " image-task-body" : taskId === "guidance" ? " context-guidance-body" : ""}`}
          >
            {viewTabs && (
              <Tabs
                id={`${taskId}-views`}
                label={`${selectedTask?.title || stage.title} views`}
                variant="secondary"
                value={taskView}
                disabled={disabled}
                onChange={stepTask}
                items={viewTabs}
              />
            )}
            <TaskHeader
              headingRef={headingRef}
              title={
                heading?.title ||
                selectedTask?.title ||
                phaseLabels[runPhase(state)] + " run"
              }
              description={heading?.description ?? selectedTask?.description}
              actions={
                <>
                  {heading?.actions}
                  {/* Playtesting checks the applied text in the game. */}
                  {position.step === "check" && state.engine === "MVMZ" && (
                    <Button
                      variant="quiet"
                      disabled={disabled}
                      onClick={() => setPanel("tools")}
                    >
                      Playtest tools
                    </Button>
                  )}
                </>
              }
            />
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
              ["translate", "check", "release"].includes(position.step) &&
              !hostedFooter && (
                <Notice tone="warning">
                  <span>
                    {fileCount(changed.length)} changed in the game. Reload them
                    from the game before new work.
                  </span>
                  {position.step !== "translate" &&
                    task(
                      "refresh_sources",
                      "Reload from game…",
                      {},
                      !preserved || !!activeOperation,
                      "default",
                      changed,
                    )}
                </Notice>
              )}
            {setupNotice && taskId === "names" && (
              <p className="guided-success" role="status">
                {setupNotice}
              </p>
            )}
            <ErrorBoundary resetKey={`${taskId}:${taskView}`} label="This task">
              {content}
            </ErrorBoundary>
          </PageBody>
          {hostedFooter ? (
            <div className="footer-slot" ref={setTaskFooter} />
          ) : (
            <ActionBar
              feedback={
                <div className="guided-footer-context">
                  {back()}
                  {actionContext || (status && <span>{status}</span>)}
                </div>
              }
            >
              {secondary}
              {taskAction}
              {taskNext}
            </ActionBar>
          )}
        </div>
      </div>
      {editorAssets && taskId === "images" && (
        <ImageTextEditor
          projectId={project.id}
          assetIds={editorAssets}
          observationKey={application.snapshot}
          onClose={() => setEditorAssets(null)}
        />
      )}
      <GuidedPanel w={w} />
      <GuidedDialogs w={w} />
      <ActionReview w={w} />
      <PendingReview pending={w.pending} />
    </PageLayout>
  );
}
