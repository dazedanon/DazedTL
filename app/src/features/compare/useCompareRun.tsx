import { api } from "../../api/client";
import type { Job } from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { ActionControl } from "../../ui/ActionControl";
import type { CompareContext } from "./Compare";
import { Button } from "../../ui/Button";
import {
  current,
  formatCost,
  runStatus,
  runStep,
  working,
  type CompareChoices,
} from "./compareView";

/**
 * One tab's comparison of its choices now, and its footer's run control:
 * Estimate cost, then Translate at the price the estimate found, whose click
 * approves sending those requests once, then Estimate again. Each action
 * stays busy until the page has read the comparisons it changed, so a
 * second click acts on what the first one started.
 */
export function useCompareRun(
  context: CompareContext,
  choices: CompareChoices,
  {
    blocked = "",
    namesHidden = false,
    started,
  }: {
    /** Why the choices can't be estimated yet. */
    blocked?: string;
    /** Whether the models' names are hidden, which its status keeps. */
    namesHidden?: boolean;
    /** Runs once a translation starts, such as to keep its names hidden. */
    started?: (job: Job) => Promise<unknown>;
  } = {},
) {
  const action = useAction({ observer: context.observer });
  const { latest, shown } = current(context.comparisons, choices);
  const step = runStep(latest, shown);
  const estimate = () =>
    action.run(
      async () => {
        try {
          return await api.compare.estimate(
            context.projectId,
            choices.kind,
            choices.file,
            choices.lines,
            [...choices.candidates],
          );
        } catch (error) {
          // A refusal for changed guidance shows the game's as it is now,
          // which Reset starts a test from.
          await context.reload();
          throw error;
        }
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
          // A refusal of an estimate already used shows its translation
          // once read; any other keeps Translate, its reason beside it.
          await context.reload();
          throw error;
        }
        await started?.(job);
      },
      "",
      "translate",
    );
  const pending = (key: string) => action.busy && action.key === key;
  const failure = (key: string) => (action.key === key ? action.error : "");
  const operation = (label: string) =>
    latest && runStatus(latest, label, namesHidden);
  /** Whether the control gives way to a primary of the tab's own, which
   * only Estimate again does. */
  const yields = step.step === "estimate" && step.again && !step.reason;
  /**
   * The footer's run control; `secondary` makes Estimate again a secondary
   * button beside the tab's own primary, such as Use the most picked model.
   */
  const control = (secondary = false) => {
    if (step.step === "translate")
      return (
        <>
          {failure("translate") && (
            // A refusal may need a new estimate, such as after the game
            // changed; the reason beside Translate says which.
            <Button disabled={action.busy} onClick={() => void estimate()}>
              Estimate again
            </Button>
          )}
          <ActionControl
            variant="primary"
            label={`Translate · about ${formatCost(step.cost)}`}
            pending={pending("translate") || pending("estimate")}
            pendingText={
              pending("estimate")
                ? "Starting the estimate…"
                : "Starting the translation…"
            }
            error={failure("translate") || failure("estimate")}
            disabled={!!blocked}
            disabledReason={blocked}
            note={
              step.left.length
                ? `Leaves out ${step.left.join(" and ")}, which couldn’t be estimated.`
                : ""
            }
            onClick={() => latest && void translate(latest.id)}
          />
        </>
      );
    if (step.step === "translating")
      return (
        <ActionControl
          variant="primary"
          label={`Translate · about ${formatCost(step.cost)}`}
          pendingText="Translating…"
          job={operation("Translation")}
        />
      );
    return (
      <ActionControl
        variant={secondary && yields ? undefined : "primary"}
        label={step.again ? "Estimate again" : "Estimate cost"}
        pending={pending("estimate")}
        pendingText="Starting the estimate…"
        error={failure("estimate")}
        disabled={!!blocked}
        disabledReason={blocked}
        note={
          step.reason ||
          (step.again ? "" : "Estimating is free and sends nothing.")
        }
        job={
          latest && latest.status !== "complete"
            ? operation(
                latest.stage === "translation" ? "Translation" : "Estimate",
              )
            : undefined
        }
        onClick={() => void estimate()}
      />
    );
  };
  /** What the grid says while it has no lines: what runs, or `idle`. */
  const empty = (idle: string) =>
    latest && working(latest.status)
      ? latest.stage === "translation"
        ? "Translating these lines…"
        : "Reading these lines and pricing them…"
      : idle;
  return { latest, shown, control, yields, action, empty };
}
