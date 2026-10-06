import type { GuidedStep } from "../../api/contracts";
import { Check } from "lucide-react";
import { Button } from "../../ui/Button";
import type { WorkflowStage } from "./workflow";

export function WorkflowNavigation({
  stages,
  step,
  completed,
  disabled,
  move,
  taskFor,
}: {
  stages: WorkflowStage[];
  step: GuidedStep;
  completed: ReadonlySet<string>;
  disabled: boolean;
  move: (step: GuidedStep, task: string) => void;
  taskFor: (stage: WorkflowStage) => string;
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
            {/* A stepper: the number becomes a check once every task is done. */}
            <span
              className="guided-stage-marker"
              data-state={done ? "done" : started ? "started" : undefined}
            >
              {done ? (
                <Check size={12} strokeWidth={3} aria-hidden="true" />
              ) : (
                index + 1
              )}
            </span>
            {stage.short}
            {(done || started) && (
              <span className="sr-only">
                {done ? "Tasks completed" : "In progress"}
              </span>
            )}
          </Button>
        );
      })}
    </nav>
  );
}
