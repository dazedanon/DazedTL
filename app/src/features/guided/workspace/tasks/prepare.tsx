import { PathInput } from "../../../../ui/PathInput";
import { FolderOpen } from "lucide-react";
/** Prepare: preserve the original, extract Ace data, format files and save the baseline. */
import type { ReactNode } from "react";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { Notice } from "../../../../ui/Notice";
import { Message } from "../../../../ui/Feedback";
import { FieldRow } from "../../../../ui/FieldRow";
import { JobStatus } from "../../../../ui/JobStatus";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import { StatusIcon } from "../../../../ui/StatusIcon";
import { sentence } from "../../../../ui/displayText";

export function backupView(w: GuidedWorkspace): TaskView {
  const {
    action,
    openProject,
    sourceBackup,
    preserved,
    localOperation,
    backupPending,
    stopOperation,
    advance,
    operationJob,
    task,
  } = w;
  let content: ReactNode;
  content = (
    <>
      {sourceBackup ? (
        <div className="guided-backup-location">
          <strong className={preserved ? "guided-success" : ""}>
            {preserved
              ? `${sourceBackup.files.toLocaleString()} original files preserved`
              : "Original backup unavailable"}
          </strong>
          {!preserved && (
            <Message
              message={
                sourceBackup.issue ||
                "A replacement saves the current game; it cannot recover the missing original."
              }
            />
          )}
          {preserved && (
            <Button variant="link" onClick={() => openProject("backups")}>
              Backups & recovery
            </Button>
          )}
        </div>
      ) : (
        <p className="muted">
          A recovery copy will be saved inside this game’s folder.
        </p>
      )}
      {!preserved && operationJob("backup_source") && (
        <JobStatus
          compact
          job={{
            ...operationJob("backup_source")!,
            label: "Back up original game",
          }}
        />
      )}
      {sourceBackup && !preserved && (
        <Button onClick={() => openProject("backups")}>
          Recover a saved backup
        </Button>
      )}
    </>
  );
  const run =
    !preserved &&
    task(
      "backup_source",
      backupPending
        ? "Backing up…"
        : sourceBackup
          ? "Back up current game"
          : "Back up original game",
      {},
      false,
      "primary",
    );
  const secondary = localOperation && (
    <Button
      disabled={action.busy}
      onClick={() => stopOperation(localOperation)}
    >
      Stop backup
    </Button>
  );
  const next = advance(undefined, undefined, preserved ? "primary" : "quiet");
  return { content, secondary, action: run, next };
}

export function extractView(w: GuidedWorkspace): TaskView {
  const { state, preserved, advance, task } = w;
  let content: ReactNode;
  content = (
    <>
      <p>
        {state.encrypted.length
          ? "An encrypted archive was found."
          : "No encrypted archive found."}{" "}
        {state.files.length
          ? "Converted JSON is available."
          : "Convert native Ace data to JSON before translation."}
      </p>
      {!state.aceAvailable && (
        <p className="muted">
          Native conversion requires a supported Windows environment. Existing
          ace_json exports can be used.
        </p>
      )}
      <ActionList>
        <ActionRow
          title="Encrypted archive"
          description="Extract it when the game ships one."
        >
          {task(
            "ace_decrypt",
            "Extract archive",
            {},
            !preserved || !state.encrypted.length || !state.aceAvailable,
          )}
        </ActionRow>
        <ActionRow
          title="Native game data"
          description="Convert it to JSON for the translation phases."
        >
          {task(
            "ace_extract",
            "Convert to JSON",
            {},
            !preserved || !state.aceAvailable,
          )}
        </ActionRow>
      </ActionList>
    </>
  );
  return { content, next: advance() };
}

export function formatView(w: GuidedWorkspace): TaskView {
  const {
    action,
    setPanel,
    preserved,
    baseline,
    localOperation,
    preparationPending,
    stopOperation,
    stepTask,
    advance,
    operationJob,
    task,
    preparation,
    preparationComplete,
    aceNeedsExport,
  } = w;
  let content: ReactNode;
  content = (
    <>
      {aceNeedsExport && !baseline && (
        <div className="guided-prerequisite">
          <strong>Convert Ace data first</strong>
          <Button variant="link" onClick={() => stepTask("extract")}>
            Return to Ace extraction
          </Button>
        </div>
      )}
      {baseline && !preparationComplete ? (
        <p className="guided-success">
          The version baseline is already saved. Preparation does not need to be
          repeated.
        </p>
      ) : (
        <ActionList>
          {preparation.stages.map((item) => (
            <ActionRow
              key={item.action}
              label={
                <>
                  <span className="status-heading">
                    <StatusIcon
                      status={
                        item.status === "complete"
                          ? "done"
                          : item.status === "running"
                            ? "active"
                            : item.status === "failed"
                              ? "failed"
                              : "idle"
                      }
                    />
                    <strong>{item.label}</strong>
                    {/* A stage not yet started needs no word until a run
                        queues it; its icon already shows it is not done. */}
                    {item.status !== "complete" &&
                      (item.status !== "pending" || preparationPending) && (
                        <span className="status-heading-state">
                          {item.status === "pending"
                            ? "Waiting"
                            : sentence(item.status)}
                        </span>
                      )}
                  </span>
                  {item.message && <small>{item.message}</small>}
                </>
              }
            />
          ))}
        </ActionList>
      )}
      {preparation.configuration && (
        <Notice tone={preparation.configurationReady ? "neutral" : "warning"}>
          <span>{preparation.configuration}</span>
          {!preparation.configurationReady && (
            <Button
              variant="link"
              onClick={() =>
                action.run(
                  () => window.dazedtl.openFolder("project"),
                  "Game folder opened.",
                  "open-game",
                )
              }
            >
              <FolderOpen size={14} aria-hidden="true" />
              Open game folder
            </Button>
          )}
        </Notice>
      )}
      {/* The stage rows already show a running preparation stage by stage. */}
      {localOperation && baseline && !preparationComplete && (
        <JobStatus
          compact
          job={{
            ...localOperation,
            label: localOperation.label || "Current operation",
          }}
        />
      )}
      {!localOperation &&
        !preparationComplete &&
        operationJob("prepare_game") &&
        operationJob("prepare_game")!.status !== "complete" &&
        !preparation.stages.some((item) => item.message) && (
          <JobStatus
            compact
            job={{
              ...operationJob("prepare_game")!,
              label: "Prepare game files",
            }}
          />
        )}
      <Button variant="link" onClick={() => setPanel("preparation")}>
        Preparation tools
      </Button>
    </>
  );
  const done = (preparationComplete || baseline) && !preparationPending;
  const run =
    !done &&
    task(
      "prepare_game",
      preparationPending ? "Preparing game files…" : "Prepare game files",
      {},
      !preserved || aceNeedsExport,
      "primary",
    );
  const secondary = localOperation && (
    <Button
      disabled={action.busy}
      onClick={() => stopOperation(localOperation)}
    >
      Stop preparation
    </Button>
  );
  const next = advance(undefined, undefined, done ? "primary" : "quiet");
  return { content, secondary, action: run, next };
}

export function baselineView(w: GuidedWorkspace): TaskView {
  const {
    translation,
    preserved,
    baseline,
    editForm,
    disabled,
    stepTask,
    advance,
    task,
    chooseFolder,
    preparationComplete,
    fields,
  } = w;
  let content: ReactNode;
  content = baseline ? (
    <>
      <p className="guided-success">
        Original version {translation.git?.original_version || "baseline"} is
        saved.
      </p>
      <p className="muted">
        Next, discover the game’s speakers and prepare its translation context.
      </p>
    </>
  ) : (
    <>
      {!preparationComplete && (
        <div className="guided-prerequisite">
          <strong>Complete game preparation first</strong>
          <Button variant="link" onClick={() => stepTask("format")}>
            Return to preparation
          </Button>
        </div>
      )}
      <fieldset disabled={disabled}>
        <FieldRow id="guided-version" label="Game version">
          {(props) => (
            <input
              {...props}
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
                  onChange={(event) => editForm("original", event.target.value)}
                />
                <Button onClick={() => chooseFolder("original")}>
                  Browse…
                </Button>
              </div>
            )}
          </FieldRow>
        )}
      </fieldset>
    </>
  );
  const save =
    !baseline &&
    task(
      "git_setup",
      "Review version baseline",
      {
        version: fields.version,
        original: fields.untranslated ? "" : fields.original,
        untranslated: fields.untranslated,
      },
      !preserved
        ? "Back up the original game first."
        : !preparationComplete
          ? "Prepare the game files first."
          : !fields.version.trim() && fields.untranslated === null
            ? "Enter the game version and choose its translation state."
            : !fields.version.trim()
              ? "Enter the game version."
              : fields.untranslated === null
                ? "Choose the game’s translation state."
                : !fields.untranslated && !fields.original.trim()
                  ? "Choose the matching original folder."
                  : false,
      "primary",
    );
  const next = advance(undefined, undefined, baseline ? "primary" : "quiet");
  return { content, action: save, next };
}
