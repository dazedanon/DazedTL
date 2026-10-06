/** Context: speaker investigation, translation guidance and text layout. */
import type { ReactNode } from "react";
import { api } from "../../../../api/client";
import { ActionControl } from "../../../../ui/ActionControl";
import { Button } from "../../../../ui/Button";
import { Message } from "../../../../ui/Feedback";
import { Section } from "../../../../ui/Section";
import { ContextTaskHeader, ContextWorkspace } from "../../ContextWorkspace";
import { GuidanceReview } from "../../GuidanceReview";
import { LayoutMeasurements } from "../../LayoutMeasurements";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function namesView(w: GuidedWorkspace): TaskView {
  const {
    project,
    state,
    action,
    setPanel,
    setSpeakerTab,
    headingRef,
    scan,
    investigation,
    disabled,
    stepTask,
    advance,
    feedback,
    task,
    copyTask,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  content = (
    <>
      <ContextTaskHeader
        headingRef={headingRef}
        title="Speakers & game context"
        description="Copy the task into your assistant to investigate this game."
        actions={
          <Button
            variant="quiet"
            disabled={disabled}
            onClick={() => {
              setSpeakerTab("settings");
              setPanel("speakers");
            }}
          >
            Detection settings
          </Button>
        }
      />
      <ContextWorkspace
        state={state}
        results={investigation}
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
  primary = advance(
    "Continue to guidance",
    undefined,
    investigation.every((row) => row.saved) ? "primary" : "quiet",
  );
  secondary = copyTask(
    "setup",
    "Copy investigation task",
    investigation.every((row) => row.saved) ? "default" : "primary",
  );
  return { content, primary, secondary };
}

export function guidanceView(w: GuidedWorkspace): TaskView {
  const {
    state,
    action,
    context,
    documentName,
    setDocumentName,
    headingRef,
    discovery,
    disabled,
    advance,
    feedback,
    savedNames,
    saveDocuments,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  content = (
    <>
      <ContextTaskHeader
        headingRef={headingRef}
        title="Translation guidance"
        actions={
          <ActionControl
            label="Discard draft"
            variant="quiet"
            disabled={disabled || !context.drafts[documentName]}
            {...feedback("context:discard", "Discarding…")}
            onClick={() =>
              action.run(
                () => context.discard(documentName),
                "Draft discarded.",
                "context:discard",
              )
            }
          />
        }
      />
      <GuidanceReview
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
  primary = advance("Continue to layout");
  secondary = (
    <ActionControl
      label="Save guidance"
      disabled={disabled}
      {...feedback("context:save", "Saving guidance…")}
      onClick={() => saveDocuments(savedNames)}
    />
  );
  return { content, primary, secondary };
}

export function layoutView(w: GuidedWorkspace): TaskView {
  const {
    project,
    action,
    headingRef,
    discovery,
    widthsDirty,
    save,
    disabled,
    advance,
    feedback,
    copyTask,
    widths,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  content = (
    <>
      <ContextTaskHeader
        headingRef={headingRef}
        title="Text layout"
        description="Character limits for the game’s dialogue and interface text."
      />
      <div className="context-layout">
        <p className="context-layout-status">
          {widthsDirty
            ? "Unsaved edits"
            : discovery.layoutApplication === "applied"
              ? "Set by investigation"
              : discovery.layoutStatus === "saved"
                ? "Saved"
                : "Using defaults"}
        </p>
        <Message
          message={
            action.key === "save-options" && action.error
              ? ""
              : discovery.layoutMessage || ""
          }
        />
        {discovery.layoutApplication === "pending" &&
          !discovery.layoutMessage && (
            <p className="muted">
              Measured values will be saved automatically after current work or
              option edits finish.
            </p>
          )}
        <Section title="Character limits" hint="Characters">
          {widths}
        </Section>
        <div className="context-layout-actions">
          {copyTask(
            "wrap",
            discovery.layout
              ? "Copy remeasurement task"
              : "Copy measurement task",
            "link",
          )}
        </div>
        {discovery.layout ? (
          <LayoutMeasurements layout={discovery.layout} />
        ) : (
          <p className="muted">
            Measurement is optional. You can keep the current values and
            continue.
          </p>
        )}
      </div>
    </>
  );
  primary = advance("Continue to translation");
  secondary = (
    <ActionControl
      label={
        discovery.layoutMessage && !widthsDirty
          ? "Retry measured layout"
          : "Save layout"
      }
      disabled={disabled}
      {...feedback("save-options", "Saving layout…")}
      onClick={() =>
        action.run(
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
          "Layout saved.",
          "save-options",
        )
      }
    />
  );
  return { content, primary, secondary };
}
