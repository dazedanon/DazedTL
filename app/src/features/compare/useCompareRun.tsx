import { useLayoutEffect, useState } from "react";
import { api } from "../../api/client";
import type { Comparison, Job } from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useOnChange } from "../../state/useOnChange";
import { ActionControl } from "../../ui/ActionControl";
import type { CompareContext } from "./Compare";
import { Button } from "../../ui/Button";
import { StopComparison } from "./StopComparison";
import {
  current,
  footerRuns,
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
    namesHidden = () => false,
    started,
  }: {
    /** Why the choices can't be estimated yet. */
    blocked?: string;
    /** Whether a comparison's model names are hidden, which its status
     * keeps. */
    namesHidden?: (comparison: Comparison) => boolean;
    /** Runs once a translation starts, such as to keep its names hidden. */
    started?: (job: Job) => Promise<unknown>;
  } = {},
) {
  const action = useAction({ observer: context.observer });
  const { latest, shown } = current(context.comparisons, choices);
  const step = runStep(latest, shown);
  // The footer says how the latest comparison's run goes, with its Stop, so
  // the page's notice leaves it out on this tab, told before the screen
  // paints, so the two never show at once.
  const [begun, setBegun] = useState<string | null>(null);
  // Other choices, or the started one read as the latest, leave it.
  useOnChange(latest?.id, () => setBegun(null));
  const ids = footerRuns(latest, begun);
  const { footer, running } = context;
  const footerKey = ids.join(",");
  useLayoutEffect(
    () => footer(choices.kind, footerKey ? footerKey.split(",") : []),
    [footer, choices.kind, footerKey],
  );
  const stop =
    running && ids.includes(running.id) ? (
      <StopComparison projectId={context.projectId} operation={running} />
    ) : null;
  const estimate = () =>
    action.run(
      async () => {
        try {
          const job = await api.compare.estimate(
            context.projectId,
            choices.kind,
            choices.file,
            choices.lines,
            [...choices.candidates],
          );
          setBegun(job.id);
          return job;
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
        setBegun(job.id);
        await started?.(job);
      },
      "",
      "translate",
    );
  const pending = (key: string) => action.busy && action.key === key;
  const failure = (key: string) => (action.key === key ? action.error : "");
  const operation = (label: string) =>
    latest && runStatus(latest, label, namesHidden(latest));
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
          {stop}
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
        <>
          {stop}
          <ActionControl
            variant="primary"
            label={`Translate · about ${formatCost(step.cost)}`}
            pendingText="Translating…"
            job={operation("Translation")}
          />
        </>
      );
    return (
      <>
        {stop}
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
      </>
    );
  };
  /** What the grid says while it has no lines: where they come, while the
   * footer says what runs, or `idle`. */
  const empty = (idle: string) =>
    latest && working(latest.status)
      ? "These lines show here once they are read."
      : idle;
  return { latest, shown, control, yields, action, empty };
}
