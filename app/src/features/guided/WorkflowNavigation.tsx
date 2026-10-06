import type { GuidedStep } from "../../api/contracts";
import { Button } from "../../ui/Button";
import type { WorkflowStage } from "./workflow";

export function WorkflowNavigation({
  stages,
  step,
  completed,
  disabled,
  move,
  taskFor,
  allTasks,
}: {
  stages: WorkflowStage[];
  step: GuidedStep;
  completed: ReadonlySet<string>;
  disabled: boolean;
  move: (step: GuidedStep, task: string) => void;
  taskFor: (stage: WorkflowStage) => string;
  allTasks: () => void;
}) {
  return (
    <nav className="guided-phase-nav frame-row" aria-label="Translation stages">
      {stages.map((stage, index) => {
        const done = stage.tasks.every((item) => completed.has(item.id));
        const started =
          !done && stage.tasks.some((item) => completed.has(item.id));
        return (
          <Button
            key={stage.id}
            variant="quiet"
            disabled={disabled}
            aria-current={stage.id === step ? "step" : undefined}
            onClick={() => move(stage.id, taskFor(stage))}
          >
            <span className="guided-stage-number">{index + 1}</span>
            {stage.short}
            {done ? (
              <span className="guided-completed" aria-label="Tasks completed">
                ✓
              </span>
            ) : (
              started && (
                <span className="guided-started" aria-label="In progress" />
              )
            )}
          </Button>
        );
      })}
      <Button
        variant="quiet"
        className="guided-all-tasks-button"
        onClick={allTasks}
      >
        All tasks
      </Button>
    </nav>
  );
}
