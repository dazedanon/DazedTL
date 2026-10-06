/** Apply & Fitting: publish outputs, fit text, optional QA and game tools. */
import type { ReactNode } from "react";
import { ActionControl } from "../../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { displayText } from "../../../../ui/displayText";
import { fileCount, publicationLabels } from "../model";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function applyView(w: GuidedWorkspace): TaskView {
  const {
    state,
    baseline,
    changed,
    outputFiles,
    applied,
    task,
    releaseButton,
    fileSummary,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  content = (
    <>
      {fileSummary()}
      <dl className="guided-scope-summary">
        <div>
          <dt>Saved outputs</dt>
          <dd>
            {outputFiles.length
              ? `${fileCount(outputFiles.length)} available`
              : "No selected outputs available"}
          </dd>
        </div>
        <div>
          <dt>Applied to game</dt>
          <dd>
            {!outputFiles.length
              ? "No outputs ready to apply"
              : applied
                ? state.readiness.runtime_edited.some((name) =>
                    outputFiles.includes(name),
                  )
                  ? "Previously applied"
                  : "Previously applied"
                : "Ready for application review"}
          </dd>
        </div>
      </dl>
      <p className="muted">
        Only checked files with saved output are included. Apply fully
        overwrites those game files; it does not merge changes or track
        synchronization.
      </p>

      <ActionList>
        {state.readiness.publications
          .filter(
            (row, index) =>
              index === 0 ||
              ["publishing", "recovery_needed"].includes(row.state),
          )
          .map((row) => (
            <ActionRow
              key={row.id}
              label={
                <>
                  <strong>
                    {publicationLabels[row.kind] || "Text Apply"} ·{" "}
                    {row.state === "publishing"
                      ? "Interrupted publication"
                      : row.state === "recovery_needed"
                        ? "Rollback needs recovery"
                        : row.state.replaceAll("_", " ")}
                  </strong>
                  <small>{row.files.join(", ")}</small>
                  {["publishing", "recovery_needed"].includes(row.state) && (
                    <>
                      <small>
                        {row.state === "publishing"
                          ? "This batch did not finish. Some runtime files may contain the reviewed replacement."
                          : "This batch failed, and rollback could not finish."}{" "}
                        Preserved bytes are retained. Review restore to return
                        this batch to its previous state; newer conflicting
                        edits are kept.
                      </small>
                      {!!row.recovery_errors.length && (
                        <details>
                          <summary>Saved recovery errors</summary>
                          <ul>
                            {row.recovery_errors.map((message, index) => (
                              <li key={index}>{message}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </>
                  )}
                </>
              }
            >
              {row.state !== "restored" &&
                task(
                  "runtime_restore",
                  "Review restore",
                  { publication: row.id },
                  !baseline,
                )}
            </ActionRow>
          ))}
      </ActionList>
      {state.readiness.publications.length > 1 && (
        <details>
          <summary>Earlier text batches</summary>
          <ActionList>
            {state.readiness.publications
              .slice(1)
              .filter((row) => ["complete", "restored"].includes(row.state))
              .map((row) => (
                <ActionRow
                  key={row.id}
                  label={
                    <>
                      <strong>
                        {publicationLabels[row.kind] || "Text Apply"} ·{" "}
                        {row.state}
                      </strong>
                      <small>{row.files.join(", ")}</small>
                    </>
                  }
                >
                  {row.state !== "restored" &&
                    task(
                      "runtime_restore",
                      "Review restore",
                      { publication: row.id },
                      !baseline,
                    )}
                </ActionRow>
              ))}
          </ActionList>
        </details>
      )}
      {state.engine === "ACE" && (
        <>
          <p className="muted">
            Pack the latest JSON into native data before opening the game,
            including after fitting and QA edits.
          </p>
          {task(
            "ace_pack",
            "Review native Ace packing",
            {},
            !baseline || !state.aceAvailable || !state.files.length,
          )}
        </>
      )}
    </>
  );
  primary = task(
    "export_selected",
    applied ? "Review Apply again" : "Review Apply",
    {},
    !baseline
      ? "Save a version baseline first."
      : changed.length
        ? "Resync the changed files first."
        : !outputFiles.length
          ? "No checked file has saved output yet."
          : false,
    "primary",
    outputFiles,
  );
  secondary = releaseButton;
  return {
    content,
    primary,
    secondary,
    heading: {
      title: "Apply translations",
      description: "Overwrite the checked game files with their saved output.",
    },
  };
}

export function fittingView(w: GuidedWorkspace): TaskView {
  const {
    state,
    draft,
    values,
    setPanel,
    baseline,
    layoutFiles,
    editForm,
    editText,
    disabled,
    task,
    layoutOptions,
    fitting,
    fittingSettingsSaved,
    releaseButton,
    fileSummary,
    fields,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  content = (
    <>
      <ActionList>
        <ActionRow
          label={
            <>
              <strong>Saved widths</strong>
              <small>
                Dialogue {values.widths.width} · portrait{" "}
                {values.widths.faceWidth} · list {values.widths.listWidth} ·
                notes {values.widths.noteWidth}
              </small>
            </>
          }
        >
          <Button disabled={disabled} onClick={() => setPanel("widths")}>
            Edit widths
          </Button>
        </ActionRow>
      </ActionList>
      <label className="toggle">
        <input
          type="checkbox"
          disabled={disabled}
          checked={fields.only_overflow}
          onChange={(event) => editForm("only_overflow", event.target.checked)}
        />
        Only rewrap text over its width limit
      </label>
      {fileSummary(layoutFiles.length)}
      <details>
        <summary>Fitting coverage and row protection</summary>
        <fieldset disabled={disabled} className="text-fitting-settings">
          <legend>Included text areas</legend>
          {(
            [
              ["dialogue", "Dialogue"],
              ["face_dialogue", "Dialogue with portrait"],
              ["list", "List and help descriptions"],
              ["notes", "Supported note patterns"],
            ] as const
          ).map(([key, label]) => (
            <label className="toggle" key={key}>
              <input
                type="checkbox"
                checked={fields.text.categories.includes(key)}
                onChange={(event) =>
                  editText(
                    "categories",
                    event.target.checked
                      ? [...fields.text.categories, key]
                      : fields.text.categories.filter((value) => value !== key),
                  )
                }
              />
              {label}
            </label>
          ))}
          <label>
            Event codes
            <input
              value={fields.text.codes}
              onChange={(event) => editText("codes", event.target.value)}
            />
          </label>
          <small>
            Supported: 122, 324, 325, 357, 401, 405. Choices (102), custom
            windows and arbitrary plugin text are outside this fitter.
          </small>
          <label className="toggle">
            <input
              type="checkbox"
              checked={fields.text.protect_rows}
              onChange={(event) =>
                editText("protect_rows", event.target.checked)
              }
            />
            Skip protected messages that exceed the row limit
          </label>
          <label>
            Protected row limit
            <input
              type="number"
              min={1}
              max={100}
              value={fields.text.max_rows}
              onChange={(event) =>
                editText("max_rows", Number(event.target.value))
              }
            />
          </label>
        </fieldset>
      </details>
      <p className="muted">
        Scans current runtime files. Apply translations first to fit the
        translated text. Widths count characters; they do not measure rendered
        fonts, substitutions or window height.
      </p>
      {fitting && (
        <section className="text-fit-results">
          <h3>Saved fitting scan</h3>
          <ActionList>
            <ActionRow
              label={
                <p>
                  Eligible changes:{" "}
                  {fitting.changes_found - fitting.overflow_skipped} · Protected
                  overflows skipped: {fitting.overflow_skipped}
                </p>
              }
            >
              {task(
                "rewrap_preview",
                "Scan again",
                layoutOptions,
                !baseline || !layoutFiles.length,
              )}
            </ActionRow>
          </ActionList>
          {fitting.previews.map((row, index) => (
            <details key={index}>
              <summary>
                {row.file_name} · {row.locator}
                {row.overflow && fields.text.protect_rows
                  ? ` · Skipped: ${row.rows} rows exceed the protected limit`
                  : ""}
              </summary>
              <strong>Current</strong>
              <pre>{row.before}</pre>
              <strong>Proposed</strong>
              <pre>{row.after}</pre>
            </details>
          ))}
        </section>
      )}
    </>
  );
  primary =
    state.readiness.layout_scan &&
    !draft.dirty &&
    fittingSettingsSaved &&
    !!fitting &&
    fitting.changes_found > fitting.overflow_skipped
      ? task(
          "rewrap_apply",
          "Review fitting Apply",
          layoutOptions,
          !baseline || !layoutFiles.length,
          "primary",
        )
      : task(
          "rewrap_preview",
          "Scan text fitting",
          layoutOptions,
          !baseline || !layoutFiles.length || !fields.text.categories.length,
          "primary",
        );
  secondary = releaseButton;
  return {
    content,
    primary,
    secondary,
    heading: {
      title: "Text fitting",
      description:
        "Rewrap applied text that exceeds the saved character limits.",
    },
  };
}

export function qaView(w: GuidedWorkspace): TaskView {
  const {
    action,
    baseline,
    qaTask,
    qaJob,
    qa,
    chosenFindings,
    qaStatus,
    editText,
    disabled,
    feedback,
    task,
    copyTask,
    inspect,
    releaseButton,
    fields,
  } = w;
  let content: ReactNode, primary: ReactNode, secondary: ReactNode;
  content = (
    <>
      <label>
        QA focus
        <select
          value={fields.text.focus}
          disabled={disabled}
          onChange={(event) => {
            editText("focus", event.target.value);
            editText("findings", []);
          }}
        >
          {[
            ["release", "Full game text"],
            ["database", "Database"],
            ["dialogue", "Dialogue"],
            ["risky-codes", "Risky event codes"],
          ].map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <ActionList>
        <ActionRow
          title="QA task"
          description="Prepare or resume QA for the current runtime text."
        >
          {task(
            "qa_prepare",
            "Prepare text QA task",
            { focus: fields.text.focus },
            !baseline,
          )}
        </ActionRow>
        {qaTask && (
          <ActionRow
            title="Prepared task"
            description="Paste it into your coding assistant."
          >
            <ActionControl
              label="Copy prepared QA task"
              disabled={disabled}
              {...feedback("copy:qa", "Copying…")}
              onClick={() =>
                action.run(
                  () => window.dazedtl.copyText(String(qaTask.result!.handoff)),
                  "QA task copied. Return to its saved findings when your assistant finishes.",
                  "copy:qa",
                )
              }
            />
          </ActionRow>
        )}
        <ActionRow
          title="Saved findings"
          description="Read saved reports without starting an assistant."
        >
          {task(
            "qa_status",
            "Refresh QA findings",
            { focus: fields.text.focus },
            !baseline,
          )}
        </ActionRow>
        <ActionRow
          title="Running jokes and terms"
          description="Optional investigation of recurring jokes, callbacks and terminology."
        >
          {copyTask("investigation", "Copy investigation task")}
        </ActionRow>
      </ActionList>
      <p className={qa.current ? "muted" : "guided-source-alert"}>
        {qa.message}
      </p>
      {!!qaStatus.stage && (
        <div className="guided-qa-status">
          <strong>
            Saved discovery stage:{" "}
            {displayText(qaStatus.stage).replaceAll("_", " ")}
          </strong>
          {["mechanical", "screen", "deep"].map((key) => {
            const counts = qaStatus[key] as Record<string, number> | undefined;
            return (
              counts && (
                <p key={key}>
                  {key === "screen"
                    ? "Text screening"
                    : key === "mechanical"
                      ? "Mechanical inventory"
                      : "Deep text review"}{" "}
                  · {counts.accepted ?? counts.checked ?? 0} /{" "}
                  {counts.total ?? 0}
                  {counts.unresolved
                    ? ` · ${counts.unresolved} unresolved`
                    : ""}
                </p>
              )
            );
          })}
          <small>
            Discovery completion describes these saved reports. It does not
            certify the current game as QA passed.
          </small>
          {qaJob && (
            <Button variant="quiet" onClick={() => inspect(qaJob)}>
              View saved report details
            </Button>
          )}
        </div>
      )}
      <section className="text-qa-results">
        <h3>Findings and corrections</h3>
        {!qa.findings.length && (
          <p className="muted">No saved findings returned.</p>
        )}
        {qa.findings.map((row) => (
          <details key={row.id}>
            <summary>
              {row.id} ·{" "}
              {row.classification ||
                row.category ||
                row.identity ||
                "Saved finding"}
            </summary>
            <strong>Original source</strong>
            <pre>{row.source || "Source evidence is in the saved task."}</pre>
            <strong>Current translation</strong>
            <pre>{row.current || row.live}</pre>
            <p>{row.reason || row.evidence || row.note}</p>
          </details>
        ))}
        {qa.corrections.map((row, index) => (
          <div className="text-qa-correction" key={row.finding_id + index}>
            <label className="toggle">
              <input
                type="checkbox"
                disabled={disabled || !qa.current}
                checked={chosenFindings.includes(row.finding_id)}
                onChange={(event) => {
                  editText("findings_task", qa.task || "");
                  editText(
                    "findings",
                    event.target.checked
                      ? [...new Set([...chosenFindings, row.finding_id])]
                      : chosenFindings.filter((id) => id !== row.finding_id),
                  );
                }}
              />
              {row.finding_id} · {row.file}
            </label>
            <strong>Before</strong>
            <pre>{row.expected}</pre>
            <strong>Chosen correction</strong>
            <pre>{row.replacement}</pre>
          </div>
        ))}
      </section>
    </>
  );
  primary = task(
    "qa_apply",
    "Review chosen corrections",
    {
      focus: fields.text.focus,
      task: fields.text.findings_task,
      findings: chosenFindings,
    },
    !baseline || !qa.current || !chosenFindings.length,
    "primary",
  );
  secondary = releaseButton;
  return {
    content,
    primary,
    secondary,
    heading: {
      title: "Text QA",
      description:
        "Optional. Prepare a QA task, copy it to your assistant, then review its saved findings.",
    },
  };
}

export function toolsView(w: GuidedWorkspace): TaskView {
  const {
    state,
    setPanel,
    baseline,
    release,
    disabled,
    task,
    copyTask,
    advance,
  } = w;
  let content: ReactNode, primary: ReactNode;
  content = (
    <>
      <ActionList>
        {(
          [
            ["inspector", "TL Inspector", "Open source context from the game."],
            ["forge", "Forge", "Edit text with the in-game overlay."],
          ] as const
        ).map(([key, label, description]) => (
          <ActionRow
            key={key}
            label={
              <>
                <strong>
                  {label}{" "}
                  <span
                    className={
                      state.tools?.[key].installed
                        ? "guided-completed"
                        : "muted"
                    }
                  >
                    · {state.tools?.[key].message || "Status unavailable"}
                  </span>
                </strong>
                <small>{description}</small>
              </>
            }
          >
            <div className="guided-tool-actions">
              {task(
                key + "_install",
                state.tools?.[key].installed ? "Update" : "Install",
                {},
                !baseline,
              )}
              {state.tools?.[key].present &&
                task(key + "_remove", "Remove", {}, !baseline)}
            </div>
          </ActionRow>
        ))}
        <ActionRow
          label={
            <>
              <strong>Tool settings</strong>
              <small>
                Saved: Inspector {release.tools.hotkey} · Forge{" "}
                {release.tools.forgeHotkey} · scale{" "}
                {release.tools.uiScale === "auto"
                  ? "Auto"
                  : Number(release.tools.uiScale) * 100 + "%"}
              </small>
            </>
          }
        >
          <Button disabled={disabled} onClick={() => setPanel("tools")}>
            Configure tools
          </Button>
        </ActionRow>
        <ActionRow
          title="Player walkthrough"
          description="Create a portable walkthrough with your coding assistant."
        >
          {copyTask("walkthrough", "Copy walkthrough task")}
        </ActionRow>
      </ActionList>
    </>
  );
  primary = advance();
  return {
    content,
    primary,
    heading: {
      title: "Game tools",
      description: "Optional in-game tools for checking and editing text.",
    },
  };
}
