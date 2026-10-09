import type { ReactNode } from "react";
import { StatusIcon } from "./StatusIcon";

export type StepState = "done" | "current" | "started" | "next" | "blocked";

/**
 * Where a task's steps stand inside its panel: a bar per step, green with a
 * done mark for the steps finished and accent for the current one, so the
 * next step reads at a glance. `current` past the last step marks them all
 * done. Steps someone else reports, such as an assistant's phases, give their
 * own `state`: `started` is one left unfinished behind the current step. A
 * `detail` line names what the bar alone cannot, such as Blocked.
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
            <span>
              {step.label}
              {state === "done" && (
                <StatusIcon status="done" label="Done" size={14} />
              )}
            </span>
            {step.detail && <small>{step.detail}</small>}
          </li>
        );
      })}
    </ol>
  );
}
