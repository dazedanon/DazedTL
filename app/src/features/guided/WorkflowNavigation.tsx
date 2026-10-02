import type { GuidedStep } from "../../api/contracts";
import { Button } from "../../ui/Button";
import type { WorkflowStage } from "./workflow";

export function WorkflowNavigation({ stages, step, task, completed, disabled, move }: {
  stages: WorkflowStage[]; step: GuidedStep; task: string; completed: ReadonlySet<string>;
  disabled: boolean; move: (step: GuidedStep, task: string) => void;
}) {
  return <>
    <nav className="guided-compact-nav" aria-label="Translation stages">
      {stages.map((stage, index) => <Button key={stage.id} variant="quiet" disabled={disabled}
        aria-current={stage.id === step ? "step" : undefined} onClick={() => move(stage.id, stage.tasks[0].id)}>
        <span className="guided-stage-number">{index + 1}</span>{stage.short}
      </Button>)}
    </nav>
    <nav className="guided-task-nav" aria-label="Translation tasks">
      <p className="guided-nav-label">Workflow</p>
      {stages.map((stage, index) => <div key={stage.id}>
        <Button className="guided-stage-button" variant="quiet" disabled={disabled} aria-current={stage.id === step ? "step" : undefined}
          onClick={() => move(stage.id, stage.tasks[0].id)}><span className="guided-stage-number">{index + 1}</span>{stage.title}</Button>
        {stage.id === step && stage.id !== "plugins" && <div className="guided-subtasks">{stage.tasks.map((item) => <Button key={item.id}
          variant="quiet" aria-current={item.id === task ? "step" : undefined} disabled={disabled} onClick={() => move(stage.id, item.id)}>
          {completed.has(item.id) && <span className="guided-completed" aria-label="Available">✓</span>}{item.title}
        </Button>)}</div>}
      </div>)}
    </nav>
  </>;
}
