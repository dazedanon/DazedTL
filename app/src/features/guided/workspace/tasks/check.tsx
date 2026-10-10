/** Check: the line width check and optional text QA. */
import type { ReactNode } from "react";
import { textLocation } from "../../textLocation";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { FieldRow } from "../../../../ui/FieldRow";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import {
  AssistantTask,
  type AssistantTaskState,
} from "../../../../ui/AssistantTask";
import { HelpPopover } from "../../../../ui/HelpPopover";
import { fittingCodes, fittingSummary } from "../../FittingSettings";
import { Notice } from "../../../../ui/Notice";
import { api } from "../../../../api/client";
import { jobTime } from "../model";
import { ActionControl } from "../../../../ui/ActionControl";
import { StepProgress } from "../../../../ui/StepProgress";
import { QaAuditLog, QaQuestions } from "../../TextQa";
import { qaActivity, qaPhase, qaStages, qaSummary } from "../../qaView";

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
    project,
    baseline,
    qa,
    qaJob,
    action,
    disabled,
    feedback,
    editText,
    copyTask,
    inspect,
    advance,
    fields,
    handoff,
    operationJob,
    whenFinished,
    save,
    setPanel,
  } = w;
  const phase = qaPhase(qa);
  const copied = handoff("qa").waiting;
  // An apply that failed and rolled back says so beside its retry; one from
  // before this task was prepared belongs to an earlier task.
  const applying = operationJob("qa_apply");
  const preparing = operationJob("qa_prepare");
  const applyFailed =
    phase === "ready" &&
    applying &&
    ["failed", "interrupted"].includes(applying.status) &&
    jobTime(applying) >= jobTime(preparing || {})
      ? applying.message || "The apply did not finish."
      : "";
  /** Runs one QA step; an apply or undo goes on to its checkpoint commit. */
  const step = (
    key: string,
    name: "prepare" | "apply" | "undo" | "choose",
    details: Parameters<typeof api.guided.qa>[2] = {},
    success = "",
  ) =>
    action.run(
      async () => {
        await save();
        const started = await api.guided.qa(project.id, name, details);
        if (name === "choose" || !started.operation) return;
        const ended = await whenFinished(started.operation.id);
        if (ended.status !== "complete")
          throw new Error(ended.message || "QA did not finish this step.");
        if (name === "prepare") {
          await window.dazedtl.copyText(
            (await api.guided.skill(project.id, "qa")).text,
          );
          return;
        }
        const saved = await api.guided.qa(project.id, "checkpoint");
        const committed = await whenFinished(saved.operation!.id);
        if (committed.status !== "complete")
          throw new Error(
            "The corrections are in the game, but their version was not saved: " +
              (committed.message || "the checkpoint did not finish."),
          );
      },
      success,
      key,
    );
  const start = (label: string, variant: "primary" | "default" = "primary") => (
    <ActionControl
      label={label}
      variant={variant}
      disabled={disabled || !baseline}
      disabledReason={baseline ? "" : "Set up the game first."}
      {...feedback("qa-start", "Preparing QA…")}
      onClick={() =>
        step(
          "qa-start",
          "prepare",
          {},
          "QA task copied. Paste it into your coding assistant.",
        )
      }
    />
  );
  const activity = qaActivity(qa);
  const coverage = qa.coverage;
  const panelState: AssistantTaskState =
    phase === "applied"
      ? "applied"
      : phase === "outdated"
        ? "outdated"
        : phase === "questions"
          ? "needs_review"
          : phase === "clean"
            ? "done"
            : phase === "ready"
              ? "ready"
              : copied || phase === "running"
                ? "waiting"
                : "not_started";
  const content: ReactNode = (
    <>
      {phase === "not_started" && (
        <FieldRow id="qa-focus" label="QA focus">
          {(props) => (
            <select
              {...props}
              value={fields.text.focus}
              disabled={disabled}
              onChange={(event) => editText("focus", event.target.value)}
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
      )}
      <AssistantTask
        title="Text QA"
        state={panelState}
        progress={phase === "running" ? activity : undefined}
        description={
          phase === "not_started"
            ? "Start QA to prepare its task and copy it to your assistant, which reviews the game's text and applies verified corrections."
            : phase === "outdated"
              ? "The game text changed after QA. Run QA again to check the current text."
              : phase === "running"
                ? "Your assistant is reviewing. Corrections apply on their own once they pass the editorial pass."
                : phase === "questions"
                  ? "QA needs your answer for the lines below before it applies its corrections."
                  : phase === "ready"
                    ? "Your assistant applies these corrections next; you can also apply them here."
                    : qaSummary(qa)
        }
        help="Verified corrections go into the game as one text batch, saved as a version. History can restore the batch, and Undo puts back one correction."
      >
        {qa.task && <StepProgress label="QA stages" steps={qaStages(qa)} />}
        {qa.task && (coverage?.not_reviewed || coverage?.preflight) ? (
          <p className="text-qa-coverage-line">
            {[
              `${(coverage.lines - coverage.not_reviewed).toLocaleString()} lines checked`,
              coverage.not_reviewed &&
                `${coverage.not_reviewed.toLocaleString()} not reviewed (declined by the reviewer)`,
              coverage.preflight &&
                `${coverage.preflight.toLocaleString()} Japanese QA can't correct`,
            ]
              .filter(Boolean)
              .join(" · ")}{" "}
            <Button variant="link" onClick={() => setPanel("qa-coverage")}>
              Review them
            </Button>
          </p>
        ) : null}
        {qaJob && phase !== "not_started" && (
          <Button variant="link" onClick={() => inspect(qaJob)}>
            Report details
          </Button>
        )}
      </AssistantTask>
      {qa.questions.length > 0 && !qa.applied && (
        <QaQuestions
          questions={qa.questions}
          disabled={disabled}
          feedback={feedback}
          choose={(question, choice) =>
            step(`qa-${choice}:` + question, "choose", { question, choice })
          }
        />
      )}
      {applyFailed && (
        <Notice tone="warning">
          <span>
            The apply failed and was rolled back, so the game is unchanged:{" "}
            {applyFailed}
          </span>
        </Notice>
      )}
      {qa.findings.length > 0 && phase !== "outdated" && (
        <QaAuditLog
          findings={qa.findings}
          disabled={disabled}
          feedback={feedback}
          undo={(row) =>
            step("qa-undo:" + row.id, "undo", { findings: [row.id] }, "Undone.")
          }
        />
      )}
    </>
  );
  const footer =
    phase === "not_started" ? (
      start("Start text QA")
    ) : phase === "outdated" ? (
      start("Run QA again")
    ) : phase === "ready" ? (
      <ActionControl
        label={applyFailed ? "Try again" : "Apply corrections"}
        variant="primary"
        disabled={disabled}
        {...feedback("qa-apply", "Applying…")}
        onClick={() => step("qa-apply", "apply", {}, "Corrections applied.")}
      />
    ) : phase === "running" ? (
      copyTask(
        "qa",
        "Copy QA task",
        "default",
        "QA task copied. Paste it into your coding assistant.",
      )
    ) : undefined;
  return {
    content,
    action: footer,
    next: advance(
      undefined,
      undefined,
      ["applied", "clean"].includes(phase) ? "primary" : "quiet",
    ),
    heading: {
      title: "Text QA",
      description:
        "Your assistant reviews the game's text and applies verified corrections; you answer only what it can't settle.",
    },
  };
}
