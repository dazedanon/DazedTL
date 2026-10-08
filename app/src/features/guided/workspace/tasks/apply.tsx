/** Check: apply outputs, check line widths and optional text QA. */
import type { ReactNode } from "react";
import { textLocation } from "../../textLocation";
import { ActionControl } from "../../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { CheckField, FieldRow } from "../../../../ui/FieldRow";
import { sentence } from "../../../../ui/displayText";
import { publicationLabels, publicationTitle } from "../model";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import {
  AssistantTask,
  type AssistantTaskState,
} from "../../../../ui/AssistantTask";
import { HelpPopover } from "../../../../ui/HelpPopover";
import { Notice } from "../../../../ui/Notice";
import { StatusHeading } from "../../../../ui/StatusMark";
import { selectionNames } from "../../../../ui/displayText";
import { type PendingPartId, pendingSummary } from "../../pending";
import { sinceLabel } from "../../../assistant/assistantTasks";

/** Where each pending part is worked on, for its row's link. */
const partTasks: Record<PendingPartId, [string, string]> = {
  plugins: ["plugins", "Plugin files"],
  images: ["images", "Images"],
  text: ["", ""],
  rewraps: ["fitting", "Line width check"],
  qa: ["qa", "Text QA"],
};

export function applyView(w: GuidedWorkspace): TaskView {
  const {
    state,
    baseline,
    changed,
    outputFiles,
    disabled,
    task,
    advance,
    stepTask,
    chooseFiles,
    pending,
    pendingList,
    pendingExcluded,
    setPendingExcluded,
    openPending,
  } = w;
  const included = pendingList.filter(
    (part) => !pendingExcluded.has(part.id) && !part.held,
  );
  const toggle = (id: PendingPartId) =>
    setPendingExcluded((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const textChanged =
    !!changed.length && included.some((part) => part.id === "text");
  let content: ReactNode;
  content = (
    <>
      {pendingList.length ? (
        <ActionList>
          {pendingList.map((part) => {
            const left = pendingExcluded.has(part.id);
            const [taskId, owner] = partTasks[part.id];
            return (
              <ActionRow
                key={part.id}
                label={
                  <>
                    <StatusHeading
                      state={left || part.held ? "skipped" : "ready"}
                      title={`${part.title} · ${part.summary}`}
                    />
                    <small>
                      {left
                        ? "Left out of this apply."
                        : part.held ||
                          selectionNames(part.files) ||
                          `Reviewed in ${owner}.`}
                    </small>
                  </>
                }
              >
                {taskId ? (
                  <Button
                    variant="quiet"
                    disabled={disabled}
                    onClick={() => stepTask(taskId)}
                  >
                    Open {owner}
                  </Button>
                ) : (
                  // Text applies the checked files that have saved output.
                  <Button
                    variant="quiet"
                    disabled={disabled}
                    onClick={() => chooseFiles()}
                  >
                    Choose files
                  </Button>
                )}
                <Button
                  disabled={disabled || pending.busy}
                  onClick={() => toggle(part.id)}
                >
                  {left ? "Include" : "Leave out"}
                </Button>
              </ActionRow>
            );
          })}
        </ActionList>
      ) : (
        <Notice>
          <span>Nothing is waiting to go into the game.</span>
          {!!outputFiles.length && (
            <Button
              variant="link"
              disabled={disabled || pending.busy || !baseline}
              // Its result reports beside the footer's Review & apply.
              onClick={() =>
                void openPending("text", { text: outputFiles }, "all")
              }
            >
              Apply saved text again
            </Button>
          )}
        </Notice>
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
            !baseline || !state.files.length,
          )}
        </>
      )}
    </>
  );
  const blocked = !baseline
    ? "Set up the game first."
    : textChanged
      ? "Reload the changed files from the game first."
      : !included.length
        ? pendingList.length
          ? "Include a part to apply."
          : ""
        : "";
  const review = (
    <ActionControl
      label={
        included.length
          ? `Review & apply · ${pendingSummary(included)}`
          : "Review & apply"
      }
      variant="primary"
      disabled={disabled || pending.busy || !!blocked || !included.length}
      disabledReason={blocked}
      feedbackKey="pending:review"
      pendingText="Preparing the review…"
      {...pending.feedback("all")}
      onClick={() => void openPending()}
    />
  );
  return {
    content,
    action: review,
    next: advance(
      undefined,
      undefined,
      pendingList.length ? "quiet" : "primary",
    ),
  };
}

export function fittingView(w: GuidedWorkspace): TaskView {
  const {
    state,
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
    fittingCurrent: scanCurrent,
    fittingEligible: eligible,
    reviewPending,
    advance,
    fileRow,
    fields,
  } = w;
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
                Line widths{" "}
                <HelpPopover label="Line widths">
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
            Edit line widths
          </Button>
        </ActionRow>
        <ActionRow
          label={
            <CheckField
              id="fitting-only-overflow"
              label="Only rewrap lines wider than their limit"
              checked={fields.only_overflow}
              disabled={disabled}
              onChange={(checked) => editForm("only_overflow", checked)}
            />
          }
        />
        {fileRow(layoutFiles)}
      </ActionList>
      <details>
        <summary>Checked text and row protection</summary>
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
            windows and arbitrary plugin text are outside this check.
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
          <h3>Last check</h3>
          <ActionList>
            <ActionRow
              label={
                <span>
                  {eligible
                    ? `${eligible} ${eligible === 1 ? "change" : "changes"} to review`
                    : fitting.overflow_skipped
                      ? "No changes to apply"
                      : "No line is wider than these widths."}
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
                  "Check again",
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
      ? reviewPending({
          only: "rewraps",
          label: "Review & apply rewraps",
          blocked: !baseline || !layoutFiles.length,
        })
      : task(
          "rewrap_preview",
          "Check line widths",
          layoutOptions,
          !baseline || !layoutFiles.length || !fields.text.categories.length,
          scanCurrent ? "default" : "primary",
        );
  return {
    content,
    action: run,
    // A current scan that found nothing to fit completes the task.
    next: advance(
      undefined,
      undefined,
      scanCurrent && eligible === 0 ? "primary" : "quiet",
    ),
    // Fitting reads the game's current text, so it needs applied output.
    actionContext: !state.readiness.applied.length && (
      <span>Apply translations first; the check reads the game’s text.</span>
    ),
    heading: {
      title: "Line width check",
      description:
        "Rewrap applied text that is wider than the saved line widths.",
    },
  };
}

export function qaView(w: GuidedWorkspace): TaskView {
  const {
    baseline,
    qaTask,
    qaJob,
    qa,
    chosenFindings,
    qaStatus,
    editText,
    disabled,
    task,
    copyTask,
    inspect,
    reviewPending,
    advance,
    fields,
    handoff,
  } = w;
  // The app prepares the task and its mechanical inventory itself; the
  // assistant has the task once it is copied or its screening has begun.
  const screening = handoff("qa");
  const qaCopied = screening.waiting;
  // Applying corrections changes the text this task checked, which makes it
  // stale; that and later edits are expected, not a problem.
  const qaApplied = qa.applied;
  // A finding can be chosen once its assistant prepared a correction for it.
  const operations = new Map<string, typeof qa.corrections>();
  for (const change of qa.corrections)
    operations.set(change.finding_id, [
      ...(operations.get(change.finding_id) || []),
      change,
    ]);
  const choosable = qa.findings
    .map((row) => row.id)
    .filter((id) => operations.has(id));
  const choose = (ids: string[]) => {
    editText("findings_task", qa.task || "");
    editText("findings", [...new Set(ids)]);
  };
  const qaStarted = (["screen", "deep"] as const).some((key) => {
    const counts = qaStatus[key] as Record<string, number> | undefined;
    return !!(counts?.accepted || counts?.checked);
  });
  // A finished run with no findings is done; the assistant has nothing left.
  const qaState: AssistantTaskState = qaApplied
    ? "applied"
    : // The text this task checked changed since.
      !qa.current && qaStatus.stage
      ? "outdated"
      : qa.findings.length
        ? "needs_review"
        : qaStatus.stage === "complete"
          ? "done"
          : qaCopied || qaStarted
            ? "waiting"
            : "not_started";
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
        state={qaState}
        progress={
          qaCopied && !qa.findings.length
            ? sinceLabel(screening.since)
            : undefined
        }
        description={
          // Before any result exists, "saved results match" has nothing to
          // describe; say what happens next instead.
          qaState === "applied"
            ? "Chosen corrections are applied. Restore them from Pending changes, or prepare QA again to check the current text."
            : qaState === "done"
              ? "Your assistant saved no findings for the current text."
              : qaState === "waiting"
                ? "Results appear here as your assistant saves them."
                : qaState === "not_started" && qaTask
                  ? "Copy the prepared task to your assistant."
                  : qa.message
        }
        help="Discovery describes the saved reports. It does not certify the current game as QA passed."
        results={[
          {
            id: "qa",
            title: "QA findings",
            state: qaState,
            detail: (
              <>
                {!!qa.findings.length &&
                  `${qa.findings.length.toLocaleString()} saved · `}
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
                      .join(" · ") || "No translated text to check."
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
            // It saves nothing the app can check, so it shows no state.
            detail:
              "Optional. An investigation of recurring jokes, callbacks and terminology.",
            action: copyTask("investigation", "Copy investigation task"),
          },
        ]}
      />
      {/* The QA findings row already says whether results are pending. */}
      {!!qa.findings.length && (
        <section className="text-qa-results">
          {/* One row per finding: its change, evidence and, when it has a
              prepared correction, the choice to apply it. */}
          <div className="text-qa-results-heading">
            <h3>Findings</h3>
            {!!choosable.length && !qaApplied && (
              <>
                <span className="muted">
                  {chosenFindings.length} of {choosable.length} chosen
                </span>
                <Button
                  variant="link"
                  disabled={
                    disabled ||
                    !qa.current ||
                    chosenFindings.length === choosable.length
                  }
                  onClick={() => choose(choosable)}
                >
                  Choose all
                </Button>
                <Button
                  variant="link"
                  disabled={disabled || !chosenFindings.length}
                  onClick={() => choose([])}
                >
                  Clear
                </Button>
              </>
            )}
          </div>
          <ul className="text-qa-findings">
            {qa.findings.map((row) => {
              const changes = operations.get(row.id) || [];
              const before = row.current || row.live || changes[0]?.expected;
              const after = row.correction || changes[0]?.replacement;
              const files = [...new Set(changes.map((change) => change.file))];
              return (
                <li key={row.id} data-applied={qaApplied || undefined}>
                  <input
                    hidden={qaApplied}
                    type="checkbox"
                    id={`qa-${row.id}`}
                    aria-label={`Apply ${row.id}`}
                    disabled={disabled || !qa.current || !changes.length}
                    checked={chosenFindings.includes(row.id)}
                    onChange={(event) =>
                      choose(
                        event.target.checked
                          ? [...chosenFindings, row.id]
                          : chosenFindings.filter((id) => id !== row.id),
                      )
                    }
                  />
                  <label htmlFor={`qa-${row.id}`}>
                    <span className="text-qa-change">
                      <span>{before}</span>
                      {after && (
                        <>
                          <span aria-label="becomes">→</span>
                          <strong>{after}</strong>
                        </>
                      )}
                    </span>
                    <small>
                      {[
                        row.classification ||
                          (row.category && sentence(row.category)),
                        row.source,
                        files.join(", "),
                        changes.length > 1 && `${changes.length} places`,
                        row.id,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                    {(row.reason || row.evidence || row.note) && (
                      <small>{row.reason || row.evidence || row.note}</small>
                    )}
                  </label>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </>
  );
  // The footer walks QA forward: prepare a task, copy it, then review the
  // corrections chosen from its findings. Findings checked against text that
  // has changed since lead back to preparing again, and a finished run with
  // no findings hands the lead to Continue.
  const review =
    qaApplied || (qa.findings.length && !qa.current)
      ? task(
          "qa_prepare",
          "Prepare QA again",
          { focus: fields.text.focus },
          !baseline,
        )
      : qa.findings.length
        ? reviewPending({
            only: "qa",
            label: "Review chosen corrections",
            blocked: !baseline
              ? true
              : !chosenFindings.length
                ? choosable.length
                  ? "Choose corrections first."
                  : "No finding has a prepared correction yet."
                : false,
          })
        : qaState === "done"
          ? undefined
          : qaTask
            ? copyTask(
                "qa",
                "Copy QA task",
                "primary",
                "QA task copied. Paste it into your coding assistant.",
              )
            : task(
                "qa_prepare",
                "Prepare text QA task",
                { focus: fields.text.focus },
                !baseline,
                "primary",
              );
  return {
    content,
    action: review,
    next: advance(
      undefined,
      undefined,
      qaState === "done" ? "primary" : "quiet",
    ),
    heading: {
      title: "Text QA",
      description:
        "Prepare a QA task, copy it to your assistant, then review its saved findings.",
    },
  };
}
