import { useState } from "react";
import { api } from "../../api/client";
import type { Job } from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { ActionControl } from "../../ui/ActionControl";
import type { CompareContext } from "./Compare";
import {
  current,
  estimateTotal,
  formatCost,
  working,
  type CompareChoices,
} from "./compareView";

/**
 * One tab's comparison of its choices now, and its footer's run control:
 * Estimate cost, then Translate at the price the estimate found, whose click
 * approves sending those requests once, then Estimate again.
 */
export function useCompareRun(
  context: CompareContext,
  choices: CompareChoices,
  {
    blocked = "",
    secondaryWhenDone = false,
    started,
  }: {
    /** Why the choices can't be estimated yet. */
    blocked?: string;
    /** Whether Estimate again gives way to a primary of the tab's own once
     * the lines are translated. */
    secondaryWhenDone?: boolean;
    /** Runs once a translation starts, such as to keep its names hidden. */
    started?: (job: Job) => Promise<unknown>;
  } = {},
) {
  const action = useAction();
  const { latest, shown } = current(context.comparisons, choices);
  // An estimate whose translation was refused, such as one the game changed
  // since, is estimated again; the refusal stays beside the button.
  const [refused, setRefused] = useState<ReadonlySet<string>>(new Set());
  const estimate = () =>
    action.run(
      async () => {
        await api.compare.estimate(
          context.projectId,
          choices.kind,
          choices.file,
          choices.lines,
          [...choices.candidates],
        );
        context.reload();
      },
      "",
      "estimate",
    );
  const translate = (id: string) =>
    action.run(
      async () => {
        let job: Job;
        try {
          job = await api.compare.translate(context.projectId, id);
        } catch (error) {
          setRefused((ids) => new Set(ids).add(id));
          throw error;
        }
        context.reload();
        await started?.(job);
      },
      "",
      "translate",
    );
  const pending = action.busy && ["estimate", "translate"].includes(action.key);
  const error = ["estimate", "translate"].includes(action.key)
    ? action.error
    : "";
  const priced =
    latest?.stage === "estimate" &&
    latest.status === "complete" &&
    !refused.has(latest.id)
      ? estimateTotal(latest)
      : null;
  const translating = latest?.stage === "translation";
  const operation = (label: string) =>
    latest && {
      label,
      status: latest.status,
      message: latest.message,
    };
  let control;
  if (priced) {
    const left = priced.left.map((model) => model.model);
    control = (
      <ActionControl
        variant="primary"
        label={`Translate · about ${formatCost(priced.cost)}`}
        pending={pending}
        pendingText="Starting the translation…"
        error={error}
        disabled={!!blocked || !priced.priced}
        disabledReason={
          blocked || "No model could be estimated. See each model’s error."
        }
        note={
          left.length
            ? `Leaves out ${left.join(" and ")}, which couldn’t be estimated.`
            : ""
        }
        onClick={() => void translate(latest.id)}
      />
    );
  } else if (translating && working(latest.status)) {
    const total = estimateTotal(latest);
    control = (
      <ActionControl
        variant="primary"
        label={`Translate · about ${formatCost(total.cost)}`}
        pendingText="Translating…"
        job={operation("Translation")}
      />
    );
  } else {
    const again = translating || !!shown?.translationId;
    control = (
      <ActionControl
        variant={translating && secondaryWhenDone ? undefined : "primary"}
        label={again ? "Estimate again" : "Estimate cost"}
        pending={pending}
        pendingText="Starting the estimate…"
        error={error}
        disabled={!!blocked}
        disabledReason={blocked}
        note={again ? "" : "Estimating is free and sends nothing."}
        job={
          latest && !refused.has(latest.id) && latest.status !== "complete"
            ? operation(translating ? "Translation" : "Estimate")
            : undefined
        }
        onClick={() => void estimate()}
      />
    );
  }
  /** What the grid says while it has no lines: what runs, or `idle`. */
  const empty = (idle: string) =>
    latest && working(latest.status)
      ? translating
        ? "Translating these lines…"
        : "Reading these lines and pricing them…"
      : idle;
  return { latest, shown, control, action, empty };
}
