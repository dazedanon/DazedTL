/** Context's Event text sources: the assistant's investigation and the source choices Translate covers. */
import type { ReactNode } from "react";
import { Button } from "../../../../ui/Button";
import {
  AssistantTask,
  type AssistantTaskState,
} from "../../../../ui/AssistantTask";
import { selectionNames } from "../../../../ui/displayText";
import { sinceLabel } from "../../../assistant/assistantTasks";
import { EventTextSources } from "../../EventTextSources";
import { sourceErrors } from "../../eventTextSelection";
import { fileCount } from "../model";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function auditView(w: GuidedWorkspace): TaskView {
  const {
    state,
    eventFiles,
    disabled,
    stepTask,
    advance,
    copyTask,
    fileSummary,
    handoff,
  } = w;
  const investigating = handoff("event_text");
  // A dismissed task no longer waits for its findings.
  const status =
    investigating.dismissed && state.eventText.status === "waiting"
      ? "missing"
      : state.eventText.status;
  const applied = status === "ready" && state.eventText.applied;
  const enabled = state.eventText.enabled.length;
  const taskState: AssistantTaskState = (
    {
      missing: "not_started",
      waiting: "waiting",
      ready: "done",
      stale: "outdated",
      invalid: "blocked",
    } as const
  )[status];
  let content: ReactNode;
  content = (
    <>
      {fileSummary(
        eventFiles.map((file) => file.name),
        "dialogue",
      )}
      <AssistantTask
        state={taskState}
        progress={
          status === "waiting" ? sinceLabel(investigating.since) : undefined
        }
        description={
          status === "missing"
            ? "Your assistant checks every affected use and internal reference, and returns the commands and argument keys it finds as evidence."
            : status === "waiting"
              ? "Findings appear here as your assistant saves them."
              : applied
                ? enabled
                  ? `Recommendations applied · ${enabled} ${enabled === 1 ? "source" : "sources"} enabled.`
                  : "Every source is off · nothing to translate."
                : status === "ready"
                  ? "Findings saved. Use recommendations in Source choices to apply them."
                  : state.eventText.message
        }
        help="Your assistant saves findings and applies their recommendations as source choices. It does not edit engine code, start translation or call providers."
        results={[
          {
            id: "findings",
            title: "Source findings",
            state: taskState,
            detail:
              status === "ready"
                ? "Coverage evidence for each source."
                : "Which event codes, plugin commands and scripts carry player text.",
          },
        ]}
      />
    </>
  );
  // Investigating comes first; choosing sources by hand and skipping stay
  // available.
  const ready = state.eventText.status === "ready";
  return {
    content,
    secondary: !applied && advance("Skip event codes", undefined, "quiet"),
    action:
      !ready && copyTask("advanced", "Copy investigation task", "primary"),
    // Applied findings lead on through Context; otherwise the sources are
    // chosen next.
    next: applied ? (
      advance()
    ) : (
      <Button
        variant={ready ? "primary" : "quiet"}
        disabled={disabled}
        onClick={() => stepTask("sources")}
      >
        {ready ? "Choose sources" : "Choose sources manually"}
      </Button>
    ),
    heading: {
      title: "Investigate sources",
      description:
        "Your assistant checks which event codes, plugin commands and scripts carry player text.",
    },
  };
}

export function sourcesView(w: GuidedWorkspace): TaskView {
  const {
    state,
    action,
    values,
    eventFiles,
    enabledCodes,
    edit,
    disabled,
    openSourcePicker,
    applyRecommendations,
    saveSources,
    chooseFiles,
    feedback,
    next,
    continueLabel,
  } = w;
  const target = next();
  const content = (
    <>
      <div className="translation-source-toolbar">
        <span>
          {fileCount(eventFiles.length)} selected
          {!!eventFiles.length &&
            ` · ${selectionNames(eventFiles.map((file) => file.name))}`}
        </span>
        <Button
          variant="quiet"
          disabled={disabled}
          onClick={() => chooseFiles("dialogue")}
        >
          Choose files
        </Button>
      </div>
      <EventTextSources
        state={state.eventText}
        values={values.engine_options}
        disabled={disabled}
        change={(key, value) =>
          edit("engine_options", { ...values.engine_options, [key]: value })
        }
        openPicker={openSourcePicker}
        recommendationFeedback={feedback("event-text:recommendations")}
        recommendations={applyRecommendations}
      />
    </>
  );
  // Moving on saves the choices, so the task's state follows them.
  return {
    content,
    next: target && (
      <Button
        variant="primary"
        pending={action.busy && action.key === "event-text:save"}
        disabled={
          disabled ||
          (!!enabledCodes.length &&
            !!sourceErrors(state.eventText, values.engine_options).length)
        }
        onClick={() => void saveSources(target.id)}
      >
        {continueLabel(target)}
      </Button>
    ),
    heading: {
      title: "Source choices",
      description:
        "The event codes, plugin commands and scripts Translate covers.",
    },
  };
}
