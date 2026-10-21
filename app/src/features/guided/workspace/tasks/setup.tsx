/** Set up: prepare the game files and save its version; the first change
 * keeps the original files in Git. */
import type { ReactNode } from "react";
import type { Job } from "../../../../api/contracts";
import { ActionControl } from "../../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { FieldRow } from "../../../../ui/FieldRow";
import { PathInput } from "../../../../ui/PathInput";
import type { DisplayState } from "../../../../ui/displayStatus";
import { StatusHeading } from "../../../../ui/StatusMark";
import type { GuidedWorkspace, SetupStep } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

const active = (job?: Job) =>
  !!job && ["ready", "running", "waiting"].includes(job.status);

/** One setup step: its state, its name, and what it did or is doing. */
function StepRow({
  status,
  title,
  detail,
  children,
}: {
  status: DisplayState;
  title: string;
  detail?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <ActionRow
      label={
        <>
          <StatusHeading state={status} title={title} />
          {detail && <small>{detail}</small>}
        </>
      }
    >
      {children}
    </ActionRow>
  );
}

export function setupView(w: GuidedWorkspace): TaskView {
  const {
    state,
    translation,
    action,
    disabled,
    setPanel,
    gitConfigured,
    preparation,
    preparationComplete,
    aceNeedsExport,
    running,
    localOperation,
    stopOperation,
    setupStep,
    setupJobs,
    setupFailure,
    setupAction,
    setupWorking,
    startSetup,
    editForm,
    chooseFolder,
    fields,
    advance,
  } = w;
  const done = gitConfigured && !aceNeedsExport;
  const setupRunning = setupAction.busy || setupWorking;
  // The step setup runs next shows why it stopped until a newer attempt starts.
  const stepStatus = (name: SetupStep, complete: boolean): DisplayState =>
    complete
      ? "done"
      : active(setupJobs[name])
        ? "working"
        : setupStep === name && setupFailure
          ? "blocked"
          : "not_started";

  const ace = stepStatus("ace_extract", !aceNeedsExport);
  const aceDetail =
    ace === "working"
      ? setupJobs.ace_extract!.message || "Converting…"
      : ace === "not_started"
        ? !state.encrypted.length
          ? "Converts the native data to JSON."
          : state.files.length
            ? "The game still reads its original archive. Sets it aside and keeps the converted ace_json."
            : "Extracts the encrypted archive and converts the data to JSON."
        : undefined;

  const prepared = preparationComplete || gitConfigured;
  // A setup that did a step finishes; one that did none starts.
  const started = prepared || (state.engine === "ACE" && !aceNeedsExport);
  const runningStage = preparation.stages.find(
    (stage) => stage.status === "running",
  );
  const prepare = stepStatus("prepare_game", prepared);
  const prepareDetail =
    prepare === "working"
      ? `${runningStage?.label || "Preparing"}…`
      : prepare === "not_started"
        ? `Formats game data${state.hasPlugins ? ", plugins.js" : ""} and adds GameUpdate files.`
        : undefined;

  const version = stepStatus("git_setup", gitConfigured);
  const versionDetail =
    version === "done"
      ? "Used to compare and merge later game updates."
      : version === "working"
        ? "Saving…"
        : version === "not_started"
          ? "Records this version so later game updates can be merged."
          : undefined;

  const blocked =
    running && !setupRunning
      ? "Wait for the current operation to finish."
      : gitConfigured
        ? ""
        : !fields.version.trim()
          ? "Enter the game version."
          : fields.untranslated === null
            ? "Choose whether the game already contains translations."
            : !fields.untranslated && !fields.original.trim()
              ? "Choose the matching original folder."
              : "";
  const content = (
    <>
      {!gitConfigured && (
        <fieldset disabled={disabled || setupRunning}>
          <FieldRow id="guided-version" label="Game version">
            {(props) => (
              <input
                {...props}
                className="short-control"
                value={fields.version}
                placeholder="e.g. 1.2.3"
                onChange={(event) => editForm("version", event.target.value)}
              />
            )}
          </FieldRow>
          <fieldset className="guided-baseline-choice">
            <legend>Translation state</legend>
            <label>
              <input
                type="radio"
                name="baseline-source"
                checked={fields.untranslated === true}
                onChange={() => editForm("untranslated", true)}
              />
              This game is untranslated
            </label>
            <label>
              <input
                type="radio"
                name="baseline-source"
                checked={fields.untranslated === false}
                onChange={() => editForm("untranslated", false)}
              />
              This game already contains translations
            </label>
          </fieldset>
          {fields.untranslated === false && (
            <FieldRow
              id="guided-original"
              label="Matching original folder"
              help="Choose the prepared original matching this already-translated game."
            >
              {(props) => (
                <div className="guided-folder-field">
                  <PathInput
                    {...props}
                    value={fields.original}
                    placeholder="Select matching original game folder"
                    onChange={(event) =>
                      editForm("original", event.target.value)
                    }
                  />
                  <Button onClick={() => chooseFolder("original")}>
                    Browse…
                  </Button>
                </div>
              )}
            </FieldRow>
          )}
        </fieldset>
      )}
      <ActionList>
        {state.engine === "ACE" && (
          <StepRow status={ace} title="Convert Ace data" detail={aceDetail} />
        )}
        <StepRow
          status={prepare}
          title="Prepare game files"
          detail={prepareDetail}
        />
        <StepRow
          status={version}
          title={
            gitConfigured
              ? translation.git?.original_version
                ? `Version ${translation.git.original_version} recorded`
                : "Version recorded"
              : fields.version.trim()
                ? `Record version ${fields.version.trim()}`
                : "Record this version"
          }
          detail={versionDetail}
        />
      </ActionList>
      <Button variant="link" onClick={() => setPanel("preparation")}>
        Preparation tools
      </Button>
    </>
  );
  // The step that stopped explains why beside the button, until a newer
  // attempt starts; its row keeps only the mark.
  const setupError = setupRunning ? "" : setupAction.error || setupFailure;
  const run = !done && (
    <ActionControl
      label={started ? "Finish setup" : "Set up this game"}
      variant="primary"
      disabled={disabled || setupRunning || !!blocked}
      disabledReason={blocked}
      pending={setupRunning}
      // The step rows say which step is running and how far it got.
      pendingText="Setting up…"
      error={setupError}
      onClick={startSetup}
    />
  );
  // Preparation can stop between stages.
  const secondary = localOperation &&
    localOperation.action === "prepare_game" && (
      <Button
        disabled={action.busy}
        onClick={() => stopOperation(localOperation)}
      >
        Stop
      </Button>
    );
  const next = advance(undefined, undefined, done ? "primary" : "quiet");
  return { content, secondary, action: run, next };
}
