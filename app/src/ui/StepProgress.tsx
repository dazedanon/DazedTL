import type { ReactNode } from "react";

export type StepState = "done" | "current" | "next" | "blocked";

/**
 * Where a task's steps stand inside its panel: a bar per step, filled for the
 * steps done and accent for the current one, so the next step reads at a
 * glance. `current` past the last step marks them all done. Steps someone
 * else reports, such as an assistant's phases, give their own `state`, and a
 * `detail` line names a state the bar alone cannot, such as Blocked.
 */
export function StepProgress({
  label,
  steps,
  current = 0,
}: {
  label: string;
  steps: readonly {
    id: string;
    label: string;
    state?: StepState;
    detail?: ReactNode;
  }[];
  current?: number;
}) {
  return (
    <ol className="step-progress" aria-label={label}>
      {steps.map((step, index) => {
        const state =
          step.state ??
          (index < current ? "done" : index === current ? "current" : "next");
        return (
          <li
            key={step.id}
            data-state={state}
            aria-current={state === "current" ? "step" : undefined}
          >
            {step.label}
            {step.detail && <small>{step.detail}</small>}
          </li>
        );
      })}
    </ol>
  );
}
