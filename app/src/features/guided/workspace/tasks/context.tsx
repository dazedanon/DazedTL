import { Plus } from "lucide-react";
/** Context: names and glossary, translation guidance and line widths. */
import type { ReactNode } from "react";
import { api } from "../../../../api/client";
import { ActionControl } from "../../../../ui/ActionControl";
import { Button } from "../../../../ui/Button";
import {
  AssistantTask,
  type AssistantTaskState,
} from "../../../../ui/AssistantTask";
import { Message } from "../../../../ui/Feedback";
import { CheckField } from "../../../../ui/FieldRow";
import { Section } from "../../../../ui/Section";
import { ContextWorkspace } from "../../ContextWorkspace";
import { GuidanceEditor } from "../../GuidanceEditor";
import { LayoutMeasurements } from "../../LayoutMeasurements";
import { sinceLabel } from "../../../assistant/assistantTasks";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import { shortcutKeys, shortcutLabel } from "../../../../state/useShortcut";
import type { TaskView } from "./view";

/** The optional investigation in Check follows the same choice. */
const thoroughHelp =
  "Three independent passes look for names, running jokes and speech habits instead of one. They find more, and that step uses about three times as much of your assistant's plan.";

export function namesView(w: GuidedWorkspace): TaskView {
  const {
    project,
    state,
    action,
    setPanel,
    setSpeakerTab,
    scan,
    investigation,
    disabled,
    stepTask,
    advance,
    feedback,
    task,
    copyTask,
    fields,
    editForm,
  } = w;
  let content: ReactNode;
  content = (
    <>
      <ContextWorkspace
        state={state}
        results={investigation}
        investigation={
          <CheckField
            id="guided-thorough-investigation"
            label="Thorough investigation"
            help={thoroughHelp}
            checked={fields.thorough_investigation}
            disabled={disabled}
            onChange={(checked) => editForm("thorough_investigation", checked)}
          />
        }
        actions={{
          formats: (
            <Button
              variant="quiet"
              disabled={disabled}
              onClick={() => {
                setSpeakerTab("findings");
                setPanel("speakers");
              }}
            >
              View formats
            </Button>
          ),
          names: (
            <Button
              variant="quiet"
              disabled={disabled}
              onClick={() => setPanel("speaker-names")}
            >
              {scan.available ? "View names" : "Open scan"}
            </Button>
          ),
          guidance: (
            <Button
              variant="quiet"
              disabled={disabled}
              onClick={() => stepTask("guidance")}
            >
              Open guidance
            </Button>
          ),
        }}
        addReference={
          <ActionControl
            label="Add game folder"
            icon={<Plus size={16} aria-hidden="true" />}
            disabled={disabled}
            {...feedback("reference:add", "Adding folder…")}
            onClick={async () => {
              const result = await action.run(
                async () => {
                  const folder = await window.dazedtl.chooseFolder();
                  return folder
                    ? await api.guided.referenceAdd(project.id, folder)
                    : null;
                },
                "",
                "reference:add",
              );
              if (result.ok && result.value)
                action.succeed(
                  "Reference saved. Copy the task to include it.",
                  "reference:add",
                );
            }}
          />
        }
        removeReference={(row) => (
          <ActionControl
            label="Remove"
            aria-label={`Remove reference ${row.title}`}
            variant="quiet"
            disabled={disabled}
            {...feedback("reference:remove:" + row.id, "Removing…")}
            onClick={() =>
              action.run(
                () => api.guided.referenceRemove(project.id, row.id),
                "",
                "reference:remove:" + row.id,
              )
            }
          />
        )}
        removeImported={(id) =>
          task("reference_remove", "Remove", { id }, false)
        }
      />
    </>
  );
  const done = investigation.every((row) => row.saved);
  return {
    content,
    action: copyTask(
      "setup",
      "Copy names & glossary task",
      done ? "default" : "primary",
    ),
    next: advance(
      "Continue to guidance",
      undefined,
      done ? "primary" : "quiet",
    ),
    heading: {
      description:
        "Copy the task into your assistant to find speaker names and write the glossary and game context.",
      actions: (
        <Button
          variant="quiet"
          disabled={disabled}
          onClick={() => {
            setSpeakerTab("settings");
            setPanel("speakers");
          }}
        >
          Speaker detection
        </Button>
      ),
    },
  };
}

export function guidanceView(w: GuidedWorkspace): TaskView {
  const {
    state,
    action,
    context,
    documentName,
    setDocumentName,
    discovery,
    disabled,
    advance,
    feedback,
    savedNames,
    saveDocuments,
  } = w;
  let content: ReactNode;
  content = (
    <>
      <GuidanceEditor
        documents={state.documents}
        context={context}
        setup={discovery}
        names={savedNames}
        selectedName={documentName}
        select={setDocumentName}
        disabled={disabled}
      />
    </>
  );
  const dirty = Object.keys(context.drafts).length > 0;
  const secondary = (
    <>
      {!!context.drafts[documentName] && (
        <ActionControl
          label="Discard draft"
          variant="quiet"
          disabled={disabled}
          {...feedback("context:discard", "Discarding…")}
          onClick={() =>
            action.run(
              () => context.discard(documentName),
              "Draft discarded.",
              "context:discard",
            )
          }
        />
      )}
    </>
  );
  return {
    content,
    secondary,
    action: (
      <ActionControl
        label="Save guidance"
        variant={dirty ? "primary" : "default"}
        title={`Save guidance (${shortcutLabel.save})`}
        aria-keyshortcuts={shortcutKeys.save}
        disabled={disabled}
        {...feedback("context:save", "Saving guidance…")}
        onClick={() => saveDocuments(savedNames)}
      />
    ),
    next: advance(undefined, undefined, dirty ? "quiet" : "primary"),
    heading: { title: "Translation guidance" },
    save: disabled ? undefined : () => void saveDocuments(savedNames),
  };
}

export function layoutView(w: GuidedWorkspace): TaskView {
  const {
    project,
    action,
    discovery,
    widthsDirty,
    save,
    disabled,
    advance,
    feedback,
    copyTask,
    widths,
    handoff,
  } = w;
  const measuring = handoff("line_widths");
  // Measured widths save themselves, so a measurement that came back is done,
  // never waiting for a review; one that could not be saved is blocked.
  const taskState: AssistantTaskState = discovery.layoutMessage
    ? "blocked"
    : measuring.waiting
      ? "waiting"
      : discovery.layout
        ? "done"
        : "not_started";
  const remeasure = "Remeasure only if the game's windows or fonts change.";
  let content: ReactNode;
  content = (
    <>
      <div className="context-layout">
        <Message
          message={
            action.key === "save-options" && action.error
              ? ""
              : discovery.layoutMessage || ""
          }
        />
        <Section
          title="Characters per line"
          hint={
            widthsDirty
              ? "Unsaved edits"
              : discovery.layoutApplication === "applied"
                ? "Measured"
                : discovery.layoutStatus === "saved"
                  ? "Saved"
                  : "Using defaults"
          }
        >
          {widths}
        </Section>
        <AssistantTask
          state={taskState}
          progress={sinceLabel(measuring.since)}
          description={
            taskState === "blocked"
              ? "Retry measured widths to save them, or keep the current widths and continue."
              : taskState === "waiting"
                ? "Measured widths are saved automatically when your assistant reports them."
                : taskState === "done"
                  ? discovery.layoutApplication === "pending"
                    ? "Measured widths are saved automatically after current work or option edits finish."
                    : discovery.layoutApplication === "manual"
                      ? `Your edited widths are kept. ${remeasure}`
                      : `The measured widths are saved above. ${remeasure}`
                  : "Optional. Your assistant measures the game's message windows and fonts; you can keep the current widths and continue."
          }
          results={[
            {
              id: "layout",
              title: "Measured widths",
              state: taskState,
              detail:
                "Dialogue, portrait, list and note widths from the game's own layout.",
              action: copyTask(
                "wrap",
                discovery.layout
                  ? "Copy remeasurement task"
                  : "Copy measurement task",
              ),
            },
          ]}
        >
          {discovery.layout && <LayoutMeasurements layout={discovery.layout} />}
        </AssistantTask>
      </div>
    </>
  );
  const saveLayout = () =>
    void action.run(
      async () => {
        await save();
        const current = await api.guided.context(project.id, true);
        if (current.layoutMessage) throw new Error(current.layoutMessage);
        await api.guided.reviewContext(
          project.id,
          "layout",
          current.layoutRevision,
          "layout",
        );
      },
      "Line widths saved.",
      "save-options",
    );
  const pending = widthsDirty || !!discovery.layoutMessage;
  const saveControl = (
    <ActionControl
      label={
        discovery.layoutMessage && !widthsDirty
          ? "Retry measured widths"
          : "Save line widths"
      }
      variant={pending ? "primary" : "default"}
      title={`Save line widths (${shortcutLabel.save})`}
      aria-keyshortcuts={shortcutKeys.save}
      disabled={disabled}
      {...feedback("save-options", "Saving line widths…")}
      onClick={saveLayout}
    />
  );
  return {
    content,
    action: saveControl,
    next: advance(undefined, undefined, pending ? "quiet" : "primary"),
    save: disabled ? undefined : saveLayout,
  };
}
