import { api } from "../../api/client";
import type { TranslationJob, TranslationState } from "../../api/contracts";
import { flushDrafts } from "../../state/leaveGuards";
import type { useAction } from "../../state/useAction";
import { ActionControl } from "../../ui/ActionControl";
import { ActionRow } from "../../ui/ActionList";
import { StatusPanel } from "../../ui/StatusPanel";

/**
 * Lines the assistant would not translate. Another model translates them
 * from the same requests, and the assistant picks them up once saved.
 */
export function DeclinedLines({
  run,
  finishing,
  state,
  action,
}: {
  run: TranslationJob;
  /** The API run already translating them, which its own panel shows. */
  finishing: TranslationJob | undefined;
  state: TranslationState;
  action: ReturnType<typeof useAction>;
}) {
  const lines = run.declined_units;
  const translating = run.counts.pending > 0;
  return (
    <StatusPanel
      title="Declined lines"
      // While an API run holds them, its panel asks for the decision.
      state={finishing ? "waiting" : "needs_review"}
      progress={`${lines.toLocaleString()} ${lines === 1 ? "line" : "lines"}`}
      description={`Your assistant wouldn't translate ${lines === 1 ? "this line" : "these lines"} and carried on. Another model can translate them, and your assistant picks them up once they're saved.`}
    >
      {!finishing && (
        <ActionRow
          title="Translate with your API connection"
          description={
            state.connection?.model
              ? `Estimates the cost with ${state.connection.name} · ${state.connection.model}. Nothing is sent until you approve it.`
              : "Add an API connection in Settings to estimate the cost."
          }
        >
          <ActionControl
            label="Estimate"
            disabled={
              !state.connection?.model ||
              translating ||
              state.active ||
              action.busy
            }
            disabledReason={
              !state.connection?.model
                ? ""
                : translating
                  ? "Your assistant is still translating."
                  : state.active
                    ? "Wait for the current work to finish."
                    : ""
            }
            pending={action.busy && action.key === "estimate-declined"}
            pendingText="Estimating…"
            error={action.key === "estimate-declined" ? action.error : ""}
            onClick={() =>
              void action.run(
                async () => {
                  await flushDrafts();
                  await api.translation.finish(state.projectId, run.id);
                },
                "",
                "estimate-declined",
              )
            }
          />
        </ActionRow>
      )}
      <ActionRow
        title="Translate with another assistant"
        description="Copies a prompt that has another coding assistant translate only these lines."
      >
        <ActionControl
          label="Copy prompt"
          disabled={action.busy}
          pending={action.busy && action.key === "copy-declined"}
          pendingText="Copying…"
          error={action.key === "copy-declined" ? action.error : ""}
          notice={action.key === "copy-declined" ? action.notice : ""}
          onClick={() =>
            void action.run(
              async () => {
                await flushDrafts();
                const result = await api.translation.translatorPrompt(
                  state.projectId,
                  run.id,
                );
                await window.dazedtl.copyText(result.handoff);
              },
              "Prompt copied.",
              "copy-declined",
            )
          }
        />
      </ActionRow>
    </StatusPanel>
  );
}
