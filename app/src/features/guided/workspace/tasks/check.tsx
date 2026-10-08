/** Check: the line width check and optional text QA. */
import type { ReactNode } from "react";
import { textLocation } from "../../textLocation";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { FieldRow } from "../../../../ui/FieldRow";
import { sentence } from "../../../../ui/displayText";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import {
  AssistantTask,
  type AssistantTaskState,
} from "../../../../ui/AssistantTask";
import { HelpPopover } from "../../../../ui/HelpPopover";
import { fittingCodes, fittingSummary } from "../../FittingSettings";
import { Notice } from "../../../../ui/Notice";
import { sinceLabel } from "../../../assistant/assistantTasks";

export function fittingView(w: GuidedWorkspace): TaskView {
  const {
    state,
    values,
    setPanel,
    baseline,
    layoutFiles,
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
  const codes = fittingCodes(fields.text.codes);
  const unwrapped357 =
    values.engine_options.CODE357 === true && !codes.includes(357);
  const [scope, rewrap] = fittingSummary(fields.text, fields.only_overflow);
  const skipped = fitting?.overflow_skipped || 0;
  // What would be rewrapped leads; skipped messages follow with why.
  const changes = [...(fitting?.previews || [])].sort(
    (a, b) => Number(!!a.overflow) - Number(!!b.overflow),
  );
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
            onClick={() => editText("codes", [...codes, 357].join(","))}
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
        {fileRow(layoutFiles)}
        <ActionRow
          label={
            <>
              <strong>Checked text</strong>
              <small>{scope}</small>
              <small>{rewrap}</small>
            </>
          }
        >
          <Button disabled={disabled} onClick={() => setPanel("fitting")}>
            Edit settings
          </Button>
        </ActionRow>
      </ActionList>
      {fitting && (
        <section className="text-fit-results" aria-label="Last check">
          <div className="check-results-heading">
            <h3>
              {eligible
                ? `${eligible} ${eligible === 1 ? "rewrap" : "rewraps"} found`
                : fields.only_overflow
                  ? "No line is wider than these widths"
                  : "Nothing to rewrap"}
              {!!skipped && ` · ${skipped} skipped`}
            </h3>
            {!scanCurrent && (
              <span className="muted">From before your setting changes</span>
            )}
            {/* With rewraps found the footer applies them; checking again
                stays beside the result. Otherwise the footer checks. */}
            {scanCurrent &&
              eligible > 0 &&
              task(
                "rewrap_preview",
                "Check again",
                layoutOptions,
                !baseline || !layoutFiles.length,
                "link",
              )}
          </div>
          {changes.length < fitting.changes_found && (
            <p className="muted">
              The first {changes.length.toLocaleString()} of{" "}
              {fitting.changes_found.toLocaleString()} are listed; Apply covers
              them all.
            </p>
          )}
          {!!changes.length && (
            <ul className="text-fit-changes">
              {changes.map((row, index) => (
                <li key={index}>
                  <div className="text-fit-change-heading">
                    <span>
                      {row.file_name} · {textLocation(row.locator)}
                    </span>
                    {row.rows !== undefined && (
                      <small>
                        {row.overflow
                          ? `Skipped · would need ${row.rows} rows`
                          : `${row.rows} ${row.rows === 1 ? "row" : "rows"}`}
                      </small>
                    )}
                  </div>
                  {!row.overflow && (
                    <dl className="text-fit-change">
                      <dt>Now</dt>
                      <dd>{row.before}</dd>
                      <dt>Rewrapped</dt>
                      <dd>{row.after}</dd>
                    </dl>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
  const run =
    scanCurrent && eligible > 0
      ? reviewPending({
          only: "rewraps",
          label: `Apply ${eligible} ${eligible === 1 ? "rewrap" : "rewraps"}`,
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
            ? "Chosen corrections are applied. Prepare QA again to check the current text."
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
          <div className="check-results-heading">
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
