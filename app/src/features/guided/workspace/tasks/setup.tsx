/** Set up: back up the original, prepare the game files and save its version. */
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
    openProject,
    setPanel,
    sourceBackup,
    storedOriginal,
    preserved,
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
  const done = preserved && gitConfigured;
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

  const backup = stepStatus("backup_source", preserved);
  const backupDetail =
    backup === "done" ? (
      <>
        {`${sourceBackup!.files.toLocaleString()} original files backed up.`}{" "}
        <Button variant="link" onClick={() => openProject("backups")}>
          Backups
        </Button>
      </>
    ) : backup === "working" ? (
      setupJobs.backup_source!.message || "Backing up…"
    ) : backup === "blocked" ? undefined : storedOriginal && !sourceBackup ? (
      `This folder already holds a backup of the original from ${new Date(storedOriginal.created).toLocaleString()} (${storedOriginal.files.toLocaleString()} files), saved before it was moved, copied or opened in another profile. Setup uses it.`
    ) : sourceBackup ? (
      <>
        {sourceBackup.issue ||
          "The original backup is unavailable. Setting up saves the current game instead; it cannot recover the missing original."}{" "}
        <Button variant="link" onClick={() => openProject("backups")}>
          Recover a saved backup
        </Button>
      </>
    ) : (
      "A copy you can restore, kept inside this game’s folder."
    );

  const ace = stepStatus("ace_extract", !aceNeedsExport);
  const aceDetail =
    ace === "working"
      ? setupJobs.ace_extract!.message || "Converting…"
      : ace === "not_started"
        ? state.encrypted.length
          ? "Extracts the encrypted archive and converts the data to JSON."
          : "Converts the native data to JSON."
        : undefined;

  const prepared = preparationComplete || gitConfigured;
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
        <StepRow
          status={backup}
          title="Back up the original"
          detail={backupDetail}
        >
          {/* Its review says what saving the current files replaces. */}
          {backup === "not_started" &&
            storedOriginal &&
            !sourceBackup &&
            w.task(
              "backup_source",
              "Back up current files instead",
              {},
              disabled || setupRunning || running,
            )}
        </StepRow>
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
                ? `Version ${translation.git.original_version} saved`
                : "Version saved"
              : fields.version.trim()
                ? `Save version ${fields.version.trim()}`
                : "Save this version"
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
      label={preserved ? "Finish setup" : "Set up this game"}
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
  // Backups and preparation can stop between files or stages.
  const secondary = localOperation &&
    ["backup_source", "prepare_game"].includes(localOperation.action || "") && (
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
