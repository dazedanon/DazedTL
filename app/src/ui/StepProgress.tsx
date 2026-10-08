/**
 * Where a task's steps stand inside its panel: a bar per step, filled for the
 * steps done and accent for the current one, so the next step reads at a
 * glance. `current` past the last step marks them all done.
 */
export function StepProgress({
  label,
  steps,
  current,
}: {
  label: string;
  steps: readonly { id: string; label: string }[];
  current: number;
}) {
  return (
    <ol className="step-progress" aria-label={label}>
      {steps.map((step, index) => (
        <li
          key={step.id}
          data-state={
            index < current ? "done" : index === current ? "current" : "next"
          }
          aria-current={index === current ? "step" : undefined}
        >
          {step.label}
        </li>
      ))}
    </ol>
  );
}
