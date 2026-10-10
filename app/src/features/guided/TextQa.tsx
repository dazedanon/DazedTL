/**
 * Text QA as both methods show it: where it stands, its questions for the
 * user, its audit log and its coverage sheet.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  QaFinding,
  QaQuestion,
  QaReport,
  QaState,
} from "../../api/contracts";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { AssistantTask, type AssistantTaskState } from "../../ui/AssistantTask";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";
import { StatusMark } from "../../ui/StatusMark";
import { StepProgress } from "../../ui/StepProgress";
import type { QaStepDetails } from "./qaSteps";
import {
  qaActivity,
  qaGroups,
  qaOrigin,
  qaPhase,
  qaStages,
  qaSummary,
} from "./qaView";

export type Feedback = (
  key: string,
  pendingText?: string,
) => {
  feedbackKey: string;
  pending: boolean;
  pendingText: string;
  error: string;
  notice: string;
};

/**
 * The task's panel, then its questions, a failed apply and the corrections.
 * Each page adds its own footer and the fields it offers before QA starts.
 */
export function TextQaWork({
  qa,
  waiting,
  disabled,
  feedback,
  applyFailed,
  run,
  onCoverage,
  report,
  rerun = "Run QA again to check the text.",
  children,
}: {
  qa: QaState;
  /** The task went to an assistant that has not started on it yet. */
  waiting: boolean;
  disabled: boolean;
  feedback: Feedback;
  applyFailed: string;
  run: (
    key: string,
    name: "undo" | "choose",
    details: QaStepDetails,
    success?: string,
  ) => void;
  onCoverage: () => void;
  /** Opens the task's report, where the page has an inspector. */
  report?: ReactNode;
  /** How the user has an outdated task checked again. */
  rerun?: string;
  /** Fields before QA starts, such as its focus. */
  children?: ReactNode;
}) {
  const phase = qaPhase(qa);
  const coverage = qa.coverage;
  const undoUnavailable = qa.rules_changed
    ? "An update changed QA's rules after these corrections were applied."
    : "";
  // Once applied, only a proposal the user chose went into the game.
  const questions = qa.applied
    ? qa.questions.filter((row) => row.choice === "use")
    : qa.questions;
  const state: AssistantTaskState =
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
              : waiting || phase === "running"
                ? "waiting"
                : "not_started";
  const undo = (id: string) =>
    run("qa-undo:" + id, "undo", { findings: [id] }, "Undone.");
  return (
    <>
      {phase === "not_started" && children}
      <AssistantTask
        title="Text QA"
        state={state}
        progress={phase === "running" ? qaActivity(qa) : undefined}
        description={
          phase === "not_started"
            ? "Start QA to prepare its task and copy it to your assistant."
            : phase === "outdated"
              ? (qa.rules_changed
                  ? "An update changed QA's rules after this task was prepared. "
                  : "The game text changed after QA. ") + rerun
              : phase === "running"
                ? "Your assistant is reviewing. Corrections apply on their own once they pass the editorial pass."
                : phase === "questions"
                  ? "QA applies its corrections once you answer the questions below."
                  : phase === "ready"
                    ? "Your assistant applies these corrections next; you can also apply them here."
                    : qaSummary(qa)
        }
        help="Verified corrections go into the game as one text batch, saved as a version. Undo puts back one correction."
      >
        {qa.task ? (
          <div className="text-qa-status">
            {/* An outdated task's stages and coverage describe old text. */}
            {phase !== "outdated" && (
              <StepProgress label="QA stages" steps={qaStages(qa)} />
            )}
            <p>
              {phase !== "outdated" &&
              (coverage?.not_reviewed || coverage?.preflight) ? (
                <>
                  {[
                    // The summary that describes finished QA counts them.
                    !["applied", "clean"].includes(phase) &&
                      `${(coverage.lines - coverage.not_reviewed).toLocaleString()} lines checked`,
                    coverage.not_reviewed &&
                      `${coverage.not_reviewed.toLocaleString()} not reviewed (declined by the reviewer)`,
                    coverage.preflight &&
                      `${coverage.preflight.toLocaleString()} Japanese QA can't correct`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}{" "}
                  <Button variant="link" onClick={onCoverage}>
                    Review them
                  </Button>
                </>
              ) : null}
              {report}
            </p>
          </div>
        ) : undefined}
      </AssistantTask>
      {questions.length > 0 && phase !== "outdated" && (
        <QaQuestions
          questions={questions}
          disabled={disabled}
          undoUnavailable={undoUnavailable}
          feedback={feedback}
          choose={(question, choice) =>
            run(`qa-${choice}:` + question, "choose", { question, choice })
          }
          undo={(row) => undo(row.id)}
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
          undoUnavailable={undoUnavailable}
          feedback={feedback}
          undo={(row) => undo(row.id)}
        />
      )}
    </>
  );
}

/** Source, current text and the other side of a change, labelled. */
function Change({
  source,
  current,
  other,
  otherLabel,
}: {
  source: string;
  current: string;
  other?: string;
  otherLabel: string;
}) {
  return (
    <dl className="text-qa-change">
      <dt>Japanese</dt>
      <dd lang="ja">{source}</dd>
      <dt>Now</dt>
      <dd>{current}</dd>
      {other !== undefined && (
        <>
          <dt>{otherLabel}</dt>
          <dd>{other}</dd>
        </>
      )}
    </dl>
  );
}

/**
 * The lines QA cannot settle from the game's text. Each choice saves at
 * once; QA applies once every line has one, and an applied proposal can be
 * undone like a correction.
 */
export function QaQuestions({
  questions,
  disabled,
  undoUnavailable,
  choose,
  undo,
  feedback,
}: {
  questions: QaQuestion[];
  disabled: boolean;
  /** Why Undo cannot run, such as rules an update changed. */
  undoUnavailable: string;
  choose: (question: string, choice: "keep" | "use") => void;
  undo: (question: QaQuestion) => void;
  feedback: Feedback;
}) {
  const open = questions.filter((row) => !row.choice).length;
  // The task's own panel carries the state; this card names what is left.
  return (
    <section className="text-qa-questions" aria-label="Needs you">
      <h3>
        {open
          ? `Needs you · ${open.toLocaleString()} to answer`
          : "Your answers"}
      </h3>
      <p>Reviewers could not settle these lines from the game's text.</p>
      <ActionList>
        {questions.map((row) => (
          <ActionRow
            key={row.id}
            label={
              <>
                {row.state === "applied" ? (
                  <Change
                    source={row.source}
                    current={row.proposal || row.current}
                    other={row.current}
                    otherLabel="Was"
                  />
                ) : (
                  <Change
                    source={row.source}
                    current={row.current}
                    other={row.proposal}
                    otherLabel="Proposal"
                  />
                )}
                <small>{row.reason}</small>
                {row.places > 1 && (
                  <small>{row.places} places in the game</small>
                )}
              </>
            }
          >
            {row.state === "applied" ? (
              <ActionControl
                label="Undo"
                variant="link"
                disabled={disabled || !!undoUnavailable}
                disabledReason={undoUnavailable}
                {...feedback("qa-undo:" + row.id, "Undoing…")}
                onClick={() => undo(row)}
              />
            ) : row.state === "undone" ? (
              <span className="text-qa-choice">Undone</span>
            ) : row.choice ? (
              <span className="text-qa-choice">
                {row.choice === "use"
                  ? "Using the proposal"
                  : "Keeping the text"}
                {!row.state && row.proposal && (
                  <Button
                    variant="link"
                    disabled={disabled}
                    onClick={() =>
                      choose(row.id, row.choice === "use" ? "keep" : "use")
                    }
                  >
                    Change
                  </Button>
                )}
              </span>
            ) : (
              <>
                <ActionControl
                  label="Keep current text"
                  disabled={disabled}
                  {...feedback("qa-keep:" + row.id, "Saving…")}
                  onClick={() => choose(row.id, "keep")}
                />
                {row.proposal && (
                  <ActionControl
                    label="Use proposal"
                    disabled={disabled}
                    {...feedback("qa-use:" + row.id, "Saving…")}
                    onClick={() => choose(row.id, "use")}
                  />
                )}
              </>
            )}
          </ActionRow>
        ))}
      </ActionList>
    </section>
  );
}

/** Rows a category shows before its explicit Show all. */
const groupPreview = 10;

/**
 * Every correction, by category: what the line said, what it says now, why,
 * and Undo for an applied one. A long category shows its first rows until
 * the user asks for the rest.
 */
export function QaAuditLog({
  findings,
  disabled,
  undoUnavailable,
  undo,
  feedback,
}: {
  findings: QaFinding[];
  disabled: boolean;
  /** Why Undo cannot run, such as rules an update changed. */
  undoUnavailable: string;
  undo: (finding: QaFinding) => void;
  feedback: Feedback;
}) {
  const [expanded, setExpanded] = useState<string[]>([]);
  return (
    <div className="text-qa-log">
      {qaGroups(findings).map((group) => (
        <section key={group.category} aria-label={group.title}>
          <h3>
            {group.title} · {group.findings.length.toLocaleString()}
          </h3>
          <ActionList>
            {(expanded.includes(group.category)
              ? group.findings
              : group.findings.slice(0, groupPreview)
            ).map((row) => (
              <ActionRow
                key={row.id}
                label={
                  <>
                    <Change
                      source={row.source}
                      current={
                        row.state === "applied" ? row.correction : row.current
                      }
                      other={
                        row.state === "applied" ? row.current : row.correction
                      }
                      otherLabel={
                        row.state === "applied" ? "Was" : "Correction"
                      }
                    />
                    <small>{row.reason}</small>
                    <small>
                      {[
                        qaOrigin(row),
                        row.files.join(", "),
                        row.places > 1 && `${row.places} places`,
                        row.editorial && `Editorial: ${row.editorial}`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  </>
                }
              >
                {row.state === "applied" ? (
                  <ActionControl
                    label="Undo"
                    variant="link"
                    disabled={disabled || !!undoUnavailable}
                    disabledReason={undoUnavailable}
                    {...feedback("qa-undo:" + row.id, "Undoing…")}
                    onClick={() => undo(row)}
                  />
                ) : row.state === "undone" ? (
                  <span className="text-qa-choice">Undone</span>
                ) : null}
              </ActionRow>
            ))}
          </ActionList>
          {group.findings.length > groupPreview &&
            !expanded.includes(group.category) && (
              <Button
                variant="link"
                onClick={() =>
                  setExpanded((value) => [...value, group.category])
                }
              >
                Show all {group.findings.length.toLocaleString()}
              </Button>
            )}
        </section>
      ))}
    </div>
  );
}

/**
 * What QA did not cover: lines reviewers declined, which the user may read
 * and mark, and Japanese QA cannot correct.
 */
export function QaCoverage({
  load,
  markReviewed,
  onClose,
}: {
  load: () => Promise<QaReport>;
  markReviewed: (identities: string[]) => Promise<QaReport>;
  onClose: () => void;
}) {
  const [report, setReport] = useState<QaReport | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  // The sheet reads the report once when it opens, however often the page
  // around it renders.
  const first = useRef(load);
  useEffect(() => {
    first
      .current()
      .then(setReport, (reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
  }, []);
  const unreviewed = report?.not_reviewed.filter((row) => !row.reviewed) || [];
  return (
    <Modal label="What QA did not cover" onDismiss={onClose} size="lg">
      <DialogHeader
        title="What QA did not cover"
        description="Lines no reviewer judged, and Japanese outside what QA can correct."
        onClose={onClose}
      />
      <DialogBody className="text-qa-coverage">
        {error && <Notice tone="warning">{error}</Notice>}
        {!report && !error && <p className="muted">Loading…</p>}
        {report && (
          <>
            {report.not_reviewed.length > 0 && (
              <section aria-label="Not reviewed">
                <div className="check-results-heading">
                  <h3>
                    Not reviewed · {report.not_reviewed.length.toLocaleString()}
                  </h3>
                  {unreviewed.length > 0 && (
                    <Button
                      variant="link"
                      pending={saving}
                      onClick={() => {
                        setSaving(true);
                        markReviewed(unreviewed.map((row) => row.identity))
                          .then(setReport, (reason: unknown) =>
                            setError(
                              reason instanceof Error
                                ? reason.message
                                : String(reason),
                            ),
                          )
                          .finally(() => setSaving(false));
                      }}
                    >
                      I reviewed these
                    </Button>
                  )}
                </div>
                <p className="muted">
                  Reviewers declined these lines, so no reviewer judged them.
                </p>
                <ActionList>
                  {report.not_reviewed.map((row) => (
                    <ActionRow
                      key={row.identity}
                      label={
                        <>
                          <Change
                            source={row.source}
                            current={row.current}
                            otherLabel=""
                          />
                          <small>{row.file}</small>
                        </>
                      }
                    >
                      {row.reviewed && <StatusMark state="done" />}
                    </ActionRow>
                  ))}
                </ActionList>
              </section>
            )}
            {report.preflight_total > 0 && (
              <section aria-label="Japanese QA cannot correct">
                <h3>
                  Japanese QA can't correct ·{" "}
                  {report.preflight_total.toLocaleString()}
                </h3>
                <p className="muted">
                  Custom data files, plugin settings and lines without a saved
                  original are outside QA's inventory; translate them in their
                  own tasks.
                </p>
                <ul className="text-qa-preflight">
                  {report.preflight.map((row) => (
                    <li key={row.file + row.pointer}>
                      <small>
                        {row.file} · {row.kind}
                      </small>
                      <span lang="ja">{row.text}</span>
                    </li>
                  ))}
                </ul>
                {report.preflight.length < report.preflight_total && (
                  <p className="muted">
                    The first {report.preflight.length.toLocaleString()} are
                    listed.
                  </p>
                )}
              </section>
            )}
          </>
        )}
      </DialogBody>
    </Modal>
  );
}
