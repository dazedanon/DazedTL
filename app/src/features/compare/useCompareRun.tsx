import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { Comparison, Job } from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useOnChange } from "../../state/useOnChange";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import type { CompareContext } from "./Compare";
import { RunningStatus } from "./StopComparison";
import {
  actionFeedback,
  actionKey,
  current,
  formatCost,
  reportsRun,
  runningStatus,
  runStatus,
  runStep,
  working,
  type CompareChoices,
} from "./compareView";

/**
 * The page's comparison of its choices now, and its footer's run control,
 * by one rule: while any comparison of the game runs, one status line and
 * Stop; otherwise Estimate cost, then Translate at the price the estimate
 * found, whose click approves sending those requests once, then the next
 * step the page gives (`next`). Each action stays busy until the page has
 * read the comparisons it changed, so a second click acts on what the first
 * one started.
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
  // The run the page just started, which its latest comparison names only
  // once the page has read the comparisons again; other choices, or the
  // started one read as the latest, leave it.
  const [begun, setBegun] = useState<string | null>(null);
  useOnChange(latest?.id, () => setBegun(null));
  const { running } = context;
  const own =
    running &&
    [latest?.id, latest?.translationId, begun].includes(running.operation.id)
      ? latest
      : undefined;
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
          // A refusal for changed guidance shows the game's as it is now.
          await context.reload();
          throw error;
        }
      },
      "",
      actionKey("estimate", choices),
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
      actionKey("translate", choices),
    );
  const estimating = actionFeedback(action, "estimate", choices);
  const translating = actionFeedback(action, "translate", choices);
  /** The choices' lines are translated and nothing runs: the page's own
   * next step takes the footer. */
  const done =
    latest?.stage === "translation" &&
    !working(latest.status) &&
    step.step === "estimate" &&
    !step.reason;
  /**
   * The footer's actions: the running comparison's status and Stop, or the
   * run control, then the page's next step. `next.use` is the page's Use,
   * the one primary once the lines are translated; `next.again` offers
   * Estimate again beside it, as when a model failed or stopped.
   */
  const footer = (next: { use: ReactNode; again: boolean }) => {
    if (running)
      return (
        <RunningStatus
          projectId={context.projectId}
          operation={running.operation}
          text={runningStatus(
            running.operation.action,
            own,
            !!own && namesHidden(own),
          )}
        />
      );
    if (step.step === "translate")
      return (
        <>
          {translating.error && (
            // A refusal may need a new estimate, such as after the game
            // changed; the reason beside Translate says which.
            <Button
              disabled={action.busy || !!blocked}
              title={blocked || undefined}
              onClick={() => void estimate()}
            >
              Estimate again
            </Button>
          )}
          <ActionControl
            variant="primary"
            label={
              step.sent
                ? `Translate · about ${formatCost(step.cost)}`
                : // Every model is reused: nothing is sent or paid.
                  "Show the earlier lines"
            }
            inline
            pending={translating.pending || estimating.pending}
            pendingText={
              estimating.pending ? "Estimating…" : "Starting the translation…"
            }
            error={translating.error || estimating.error}
            disabled={!!blocked}
            disabledReason={blocked}
            onClick={() => latest && void translate(latest.id)}
          />
        </>
      );
    if (step.step === "translating")
      // The run ended a moment before the page read it again.
      return (
        <ActionControl
          variant="primary"
          label={`Translate · about ${formatCost(step.cost)}`}
          inline
          pending
          pendingText="Translating…"
        />
      );
    if (done && !next.again && !estimating.pending && !estimating.error)
      return next.use;
    return (
      <>
        <ActionControl
          // The one primary is Use when there is a model to use.
          variant={done && next.use ? undefined : "primary"}
          label={step.again ? "Estimate again" : "Estimate cost"}
          inline
          pending={estimating.pending}
          pendingText="Estimating…"
          error={estimating.error}
          disabled={!!blocked}
          disabledReason={blocked}
          note={
            step.reason ||
            (step.again ? "" : "Estimating is free and sends nothing.")
          }
          job={
            reportsRun(latest)
              ? runStatus(
                  latest,
                  latest.stage === "translation" ? "Translation" : "Estimate",
                  namesHidden(latest),
                )
              : undefined
          }
          onClick={() => void estimate()}
        />
        {done && next.use}
      </>
    );
  };
  /** What the grid says while it has no lines: where they come, while the
   * footer says what runs, when the running comparison is another's, or
   * `idle`. */
  const empty = (idle: string) =>
    running && !own
      ? "Estimate these lines once the running comparison ends."
      : latest && working(latest.status)
        ? "These lines show here once they are read."
        : idle;
  return { latest, shown, footer, action, empty, running: !!running };
}
