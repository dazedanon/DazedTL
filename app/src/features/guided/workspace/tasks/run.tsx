/** A saved run opened from History or a finished phase. */
import type { ReactNode } from "react";
import { api } from "../../../../api/client";
import { Button } from "../../../../ui/Button";
import RunPanel from "../../RunPanel";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function runView(w: GuidedWorkspace): TaskView {
  const {
    project,
    action,
    stage,
    setResume,
    running,
    job,
    stepTask,
    applyRun,
    nextRun,
  } = w;
  let content: ReactNode;
  content = job ? (
    <RunPanel
      projectId={project.id}
      hideTitle
      job={job}
      active={running && ["running", "waiting"].includes(job.status)}
      busy={action.busy || (running && job.status === "failed")}
      pendingKey={action.busy ? action.key : ""}
      error={action.key.startsWith("run:") ? action.error : ""}
      stop={() =>
        action.run(() => api.stop(project.id, job.id), "", "run:stop")
      }
      resume={() => setResume(job)}
      answer={(approved) =>
        action.run(
          () => api.answer(project.id, job.approval!.token, approved),
          "",
          "run:answer:" + approved,
        )
      }
    />
  ) : (
    <p className="muted">
      No saved translation run is available for this game.
    </p>
  );
  const next =
    job?.status === "complete" && job.mode !== "estimate" ? (
      job.mode === "speakers" ? (
        <Button variant="primary" onClick={() => stepTask("guidance")}>
          Review translation guidance
        </Button>
      ) : (
        nextRun(job)
      )
    ) : (
      <Button onClick={() => stepTask(stage.tasks[0].id)}>
        Return to tasks
      </Button>
    );
  const apply =
    job?.status === "complete" &&
    job.mode !== "estimate" &&
    job.mode !== "speakers" &&
    job.outputsAvailable
      ? applyRun(job)
      : undefined;
  return { content, action: apply, next };
}
