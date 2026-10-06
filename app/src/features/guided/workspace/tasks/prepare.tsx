/** Prepare: preserve the original, extract Ace data, format files and save the baseline. */
import { Check, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { Notice } from "../../../../ui/Notice";
import { Message } from "../../../../ui/Feedback";
import { FieldRow } from "../../../../ui/FieldRow";
import { JobStatus } from "../../../../ui/JobStatus";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function backupView(w: GuidedWorkspace): TaskView {
  const {
    action,
    setPanel,
    sourceBackup,
    preserved,
    localOperation,
    backupPending,
    stopOperation,
    advance,
    operationJob,
    task,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
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
            <Button variant="link" onClick={() => setPanel("backups")}>
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
        <Button onClick={() => setPanel("backups")}>
          Recover a saved backup
        </Button>
      )}
    </>
  );
  primary = preserved
    ? advance()
    : task(
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
  secondary = (
    <>
      {localOperation && (
        <Button
          disabled={action.busy}
          onClick={() => stopOperation(localOperation)}
        >
          Stop backup
        </Button>
      )}
      {!preserved && advance(undefined, undefined, "quiet")}
    </>
  );
  return { content, primary, secondary };
}

export function extractView(w: GuidedWorkspace): TaskView {
  const { state, preserved, advance, task } = w;
  let content: ReactNode, primary: ReactNode;
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
  primary = advance();
  return { content, primary };
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
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
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
        <ol className="guided-preparation-list">
          {preparation.stages.map((item) => (
            <li key={item.action}>
              <span
                className={
                  item.status === "complete" ? "guided-completed" : "muted"
                }
              >
                {item.status === "complete" ? (
                  <Check size={16} />
                ) : item.status === "running" ? (
                  <LoaderCircle size={16} className="job-status-spinner" />
                ) : (
                  "·"
                )}
              </span>
              <div>
                <strong>{item.label}</strong>
                {item.message && <small>{item.message}</small>}
              </div>
              {item.status !== "complete" && (
                <span className="guided-preparation-state">
                  {item.status === "pending"
                    ? "Waiting"
                    : item.status.replaceAll("_", " ")}
                </span>
              )}
            </li>
          ))}
        </ol>
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
              Open game folder
            </Button>
          )}
        </Notice>
      )}
      {localOperation && (
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
  primary =
    (preparationComplete || baseline) && !preparationPending
      ? advance()
      : task(
          "prepare_game",
          preparationPending ? "Preparing game files…" : "Prepare game files",
          {},
          !preserved || aceNeedsExport,
          "primary",
        );
  secondary = (
    <>
      {localOperation && (
        <Button
          disabled={action.busy}
          onClick={() => stopOperation(localOperation)}
        >
          Stop preparation
        </Button>
      )}
      {(!(preparationComplete || baseline) || preparationPending) &&
        advance(undefined, undefined, "quiet")}
    </>
  );
  return { content, primary, secondary };
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
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
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
                <input
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
  primary = baseline
    ? advance()
    : task(
        "git_setup",
        "Review version baseline",
        {
          version: fields.version,
          original: fields.untranslated ? "" : fields.original,
          untranslated: fields.untranslated,
        },
        !preserved ||
          !preparationComplete ||
          fields.untranslated === null ||
          !fields.version.trim() ||
          (!fields.untranslated && !fields.original.trim()),
        "primary",
      );
  secondary = !baseline && advance(undefined, undefined, "quiet");
  return { content, primary, secondary };
}
