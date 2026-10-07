/** Apply & Fitting: publish outputs, fit text, optional QA and game tools. */
import type { ReactNode } from "react";
import { textLocation } from "../../textLocation";
import { ActionControl } from "../../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { CheckField, DetailRow, FieldRow } from "../../../../ui/FieldRow";
import { displayText } from "../../../../ui/displayText";
import { fileCount, publicationLabels, publicationTitle } from "../model";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import { AssistantTask } from "../../../../ui/AssistantTask";
import { HelpPopover } from "../../../../ui/HelpPopover";
import { Notice } from "../../../../ui/Notice";

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
  let content: ReactNode;
  content = (
    <>
      {fileSummary()}
      {/* With nothing saved, Review & apply's reason says so once. */}
      {!!outputFiles.length && (
        <dl className="guided-scope-summary">
          <DetailRow label="Saved outputs">
            {fileCount(outputFiles.length)} available
          </DetailRow>
          {/* Once applied, the publication below says so with its files. */}
          {!applied && (
            <DetailRow label="Applied to game">
              Ready for application review
            </DetailRow>
          )}
        </dl>
      )}

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
                    {row.state === "publishing"
                      ? `${publicationLabels[row.kind] || "Text"} · Interrupted publication`
                      : row.state === "recovery_needed"
                        ? `${publicationLabels[row.kind] || "Text"} · Rollback needs recovery`
                        : publicationTitle(row)}
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
                      <strong>{publicationTitle(row)}</strong>
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
  const review = task(
    "export_selected",
    applied ? "Review & apply again" : "Review & apply",
    {},
    !baseline
      ? "Save a version baseline first."
      : changed.length
        ? "Reload the changed files from the game first."
        : !outputFiles.length
          ? "No checked file has saved output yet."
          : false,
    applied ? "default" : "primary",
    outputFiles,
  );
  return {
    content,
    action: review,
    next: releaseButton(applied ? "primary" : "quiet"),
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
    fileRow,
    fields,
  } = w;
  // A scan is current while its widths and options are the saved ones.
  const scanCurrent =
    state.readiness.layout_scan &&
    !draft.dirty &&
    fittingSettingsSaved &&
    !!fitting;
  const eligible = fitting
    ? fitting.changes_found - fitting.overflow_skipped
    : 0;
  // Translated plugin command text (357) loses its line breaks, so a
  // project that translates it needs 357 in fitting to wrap it again.
  const fittingCodes = fields.text.codes
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(Number);
  const unwrapped357 =
    values.engine_options.CODE357 === true && !fittingCodes.includes(357);
  let content: ReactNode;
  content = (
    <>
      {unwrapped357 && (
        <Notice tone="warning">
          <span>
            Translated plugin command text (357) loses its line breaks and is
            not included in fitting.
          </span>
          <Button
            variant="link"
            disabled={disabled}
            onClick={() => editText("codes", [...fittingCodes, 357].join(","))}
          >
            Include 357
          </Button>
        </Notice>
      )}
      <ActionList>
        <ActionRow
          label={
            <>
              <strong>
                Saved widths{" "}
                <HelpPopover label="Saved widths">
                  Widths count characters. They do not measure rendered fonts,
                  substitutions or window height.
                </HelpPopover>
              </strong>
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
        <ActionRow
          label={
            <CheckField
              id="fitting-only-overflow"
              label="Only rewrap text over its width limit"
              checked={fields.only_overflow}
              disabled={disabled}
              onChange={(checked) => editForm("only_overflow", checked)}
            />
          }
        />
        {fileRow(layoutFiles)}
      </ActionList>
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
      {fitting && (
        <section className="text-fit-results">
          <h3>Saved fitting scan</h3>
          <ActionList>
            <ActionRow
              label={
                <span>
                  {eligible
                    ? `${eligible} ${eligible === 1 ? "change" : "changes"} to review`
                    : fitting.overflow_skipped
                      ? "No changes to apply"
                      : "No text needs fitting at these widths."}
                  {!!fitting.overflow_skipped &&
                    ` · ${fitting.overflow_skipped} protected ${fitting.overflow_skipped === 1 ? "overflow" : "overflows"} skipped`}
                </span>
              }
            >
              {/* With changes found the footer reviews them; scanning again
                  stays beside the result. Otherwise the footer scans. */}
              {eligible > 0 &&
                task(
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
                {row.file_name} · {textLocation(row.locator)}
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
  const run =
    scanCurrent && eligible > 0
      ? task(
          "rewrap_apply",
          "Review & apply fitting",
          layoutOptions,
          !baseline || !layoutFiles.length,
          "primary",
        )
      : task(
          "rewrap_preview",
          "Scan text fitting",
          layoutOptions,
          !baseline || !layoutFiles.length || !fields.text.categories.length,
          scanCurrent ? "default" : "primary",
        );
  return {
    content,
    action: run,
    // A current scan that found nothing to fit completes the task.
    next: releaseButton(scanCurrent && eligible === 0 ? "primary" : "quiet"),
    // Fitting reads the game's current text, so it needs applied output.
    actionContext: !state.readiness.applied.length && (
      <span>Apply translations first; fitting scans the game’s text.</span>
    ),
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
  // The app prepares the task and its mechanical inventory itself; the
  // assistant has the task once it is copied or its screening has begun.
  const qaCopied = action.key === "copy:qa" && !!action.notice;
  const qaStarted = (["screen", "deep"] as const).some((key) => {
    const counts = qaStatus[key] as Record<string, number> | undefined;
    return !!(counts?.accepted || counts?.checked);
  });
  let content: ReactNode;
  content = (
    <>
      <FieldRow id="qa-focus" label="QA focus">
        {(props) => (
          <select
            {...props}
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
        )}
      </FieldRow>
      <AssistantTask
        state={
          !qa.current && qaStatus.stage
            ? "attention"
            : qa.findings.length
              ? "ready"
              : qaCopied || qaStarted
                ? "waiting"
                : "idle"
        }
        description={
          // Before any result exists, "saved results match" has nothing to
          // describe; say what happens next instead.
          qa.current && qaTask && !qa.findings.length && !qaStarted
            ? qaCopied
              ? "Results appear here as your assistant saves them."
              : "Copy the prepared task to your assistant."
            : qa.message
        }
        help="Discovery describes the saved reports. It does not certify the current game as QA passed."
        results={[
          {
            id: "qa",
            title: "QA findings",
            status: qa.findings.length
              ? "done"
              : qaStatus.stage
                ? "partial"
                : "idle",
            state: qa.findings.length
              ? `${qa.findings.length} saved`
              : qaTask
                ? "Task prepared"
                : "Not prepared",
            detail: (
              <>
                {qaStatus.stage
                  ? (["mechanical", "screen", "deep"] as const)
                      .map((key) => {
                        const counts = qaStatus[key] as
                          Record<string, number> | undefined;
                        // A stage with nothing to review is left out.
                        return counts?.total
                          ? `${
                              key === "screen"
                                ? "Text screening"
                                : key === "mechanical"
                                  ? "Mechanical inventory"
                                  : "Deep text review"
                            } ${(counts.accepted ?? counts.checked ?? 0).toLocaleString()} of ${counts.total.toLocaleString()}${
                              counts.unresolved
                                ? ` · ${counts.unresolved.toLocaleString()} unresolved`
                                : ""
                            }`
                          : "";
                      })
                      .filter(Boolean)
                      .join(" · ") ||
                    `Saved stage: ${displayText(qaStatus.stage).replaceAll("_", " ")}`
                  : "Prepare or resume QA for the current runtime text."}
                {qaJob && (
                  <>
                    {" "}
                    <Button variant="link" onClick={() => inspect(qaJob)}>
                      Report details
                    </Button>
                  </>
                )}
              </>
            ),
            // Preparing again refreshes a prepared task; the footer copies it.
            action:
              qaTask &&
              task(
                "qa_prepare",
                "Prepare again",
                { focus: fields.text.focus },
                !baseline,
              ),
          },
          {
            id: "investigation",
            title: "Running jokes and terms",
            status: "idle",
            state: "Optional",
            detail:
              "An investigation of recurring jokes, callbacks and terminology.",
            action: copyTask("investigation", "Copy investigation task"),
          },
        ]}
      />
      {/* The QA findings row already says whether results are pending. */}
      {(!!qa.findings.length || !!qa.corrections.length) && (
        <section className="text-qa-results">
          <h3>Findings and corrections</h3>
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
      )}
    </>
  );
  // The footer walks QA forward: prepare a task, copy it, then review the
  // corrections chosen from its findings.
  const review = qa.findings.length ? (
    task(
      "qa_apply",
      "Review chosen corrections",
      {
        focus: fields.text.focus,
        task: fields.text.findings_task,
        findings: chosenFindings,
      },
      !baseline || !qa.current || !chosenFindings.length,
      "primary",
    )
  ) : qaTask ? (
    <ActionControl
      label="Copy QA task"
      variant="primary"
      disabled={disabled}
      {...feedback("copy:qa", "Copying…")}
      onClick={() =>
        action.run(
          () => window.dazedtl.copyText(String(qaTask.result!.handoff)),
          "QA task copied. Paste it into your coding assistant.",
          "copy:qa",
        )
      }
    />
  ) : (
    task(
      "qa_prepare",
      "Prepare text QA task",
      { focus: fields.text.focus },
      !baseline,
      "primary",
    )
  );
  return {
    content,
    action: review,
    next: releaseButton(),
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
  let content: ReactNode;
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
            {task(
              key + "_install",
              state.tools?.[key].installed ? "Update" : "Install",
              {},
              !baseline,
            )}
            {state.tools?.[key].present &&
              task(key + "_remove", "Remove", {}, !baseline)}
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
  return {
    content,
    next: advance(),
    heading: {
      title: "Game tools",
      description: "Optional in-game tools for checking and editing text.",
    },
  };
}
