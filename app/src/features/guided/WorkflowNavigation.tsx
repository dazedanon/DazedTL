import type { GuidedStep } from "../../api/contracts";
import { Button } from "../../ui/Button";
import type { WorkflowStage } from "./workflow";

export function WorkflowNavigation({ stages, step, completed, disabled, move, taskFor }: {
  stages: WorkflowStage[]; step: GuidedStep; completed: ReadonlySet<string>;
  disabled: boolean; move: (step: GuidedStep, task: string) => void;
  taskFor: (stage: WorkflowStage) => string;
}) {
  return <nav className="guided-phase-nav" aria-label="Translation stages">
    {stages.map((stage, index) => { const done = stage.tasks.every(item => completed.has(item.id));
      return <Button key={stage.id} variant="quiet" disabled={disabled}
        aria-current={stage.id === step ? "step" : undefined} onClick={() => move(stage.id, taskFor(stage))}>
        <span className="guided-stage-number">{index + 1}</span>{stage.short}
        {done && <span className="guided-completed" aria-label="Tasks completed">✓</span>}
      </Button>;
    })}
  </nav>;
}
