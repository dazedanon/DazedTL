/**
 * Text QA as both methods show it: where it stands, its questions for the
 * user, its audit log and its coverage sheet.
 */

import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type {
  QaFinding,
  QaQuestion,
  QaReport,
  QaState,
  QaUntranslatedSource,
} from "../../api/contracts";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { AssistantTask, type AssistantTaskState } from "../../ui/AssistantTask";
import { Button } from "../../ui/Button";
import { changedWords } from "../../ui/changedWords";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";
import { StatusMark } from "../../ui/StatusMark";
import { StepProgress } from "../../ui/StepProgress";
import type { QaStepDetails } from "./qaSteps";
import {
  qaActivity,
  qaGroups,
  qaMayShow,
  qaNotTranslated,
  qaOrigin,
  qaPhase,
  qaSource,
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
  restorable = false,
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
  /** History on the Project page can restore a whole batch. */
  restorable?: boolean;
  /** Fields before QA starts, such as its focus. */
  children?: ReactNode;
}) {
  const phase = qaPhase(qa);
  const coverage = qa.coverage;
  const notTranslated = qa.not_translated;
  // Once applied, only a proposal the user chose went into the game.
  const questions = qa.applied
    ? qa.questions.filter((row) => row.choice === "use")
    : qa.questions;
  // New QA rules leave applied corrections without Undo; the page says so
  // once, above the rows.
  const undoUnavailable =
    !!qa.rules_changed &&
    [...questions, ...qa.findings].some((row) => row.state === "applied");
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
        help={
          "Verified corrections go into the game as one text batch, saved as a version. Undo puts back one correction" +
          (restorable
            ? ", and History on the Project page restores a whole batch."
            : ".")
        }
      >
        {qa.task ? (
          <div className="text-qa-status">
            {/* An outdated task's stages and coverage describe old text. */}
            {phase !== "outdated" && (
              <StepProgress label="QA stages" steps={qaStages(qa)} />
            )}
            <p>
              {phase !== "outdated" &&
              (coverage?.not_reviewed || notTranslated) ? (
                <>
                  {[
                    // The summary that describes finished QA counts them.
                    coverage &&
                      !["applied", "clean"].includes(phase) &&
                      `${(coverage.lines - coverage.not_reviewed).toLocaleString()} lines checked`,
                    coverage?.not_reviewed &&
                      `${coverage.not_reviewed.toLocaleString()} not reviewed (declined by the reviewer)`,
                    notTranslated && qaNotTranslated(notTranslated),
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
      {undoUnavailable && (
        <Notice>
          An update changed QA's rules after these corrections were applied, so
          Undo is no longer available. {rerun}
        </Notice>
      )}
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

/**
 * The Japanese, the text now and the other side of a change, labelled. An
 * applied change shows the text it replaced as Was, the two in the added and
 * removed colors with the words that changed marked.
 */
function Change({
  source,
  before,
  after,
  afterLabel = "",
  applied = false,
}: {
  source: string;
  /** The line as it was before the change. */
  before: string;
  /** The change's text, when it has one. */
  after?: string;
  /** What a change not yet in the game is called, such as "Correction". */
  afterLabel?: string;
  applied?: boolean;
}) {
  const words = useMemo(
    () =>
      applied && after !== undefined ? changedWords(before, after) : undefined,
    [applied, before, after],
  );
  return (
    <dl className="text-qa-change">
      <dt>Japanese</dt>
      <dd lang="ja">{source}</dd>
      {words ? (
        <>
          <dt data-change="added">Now</dt>
          <dd data-change="added">
            {words.after.map((run, index) => (
              <Fragment key={index}>
                {run.changed ? <ins>{run.text}</ins> : run.text}
              </Fragment>
            ))}
          </dd>
          <dt data-change="removed">Was</dt>
          <dd data-change="removed">
            {words.before.map((run, index) => (
              <Fragment key={index}>
                {run.changed ? <del>{run.text}</del> : run.text}
              </Fragment>
            ))}
          </dd>
        </>
      ) : (
        <>
          <dt>Now</dt>
          <dd>{before}</dd>
          {after !== undefined && (
            <>
              <dt>{afterLabel}</dt>
              <dd>{after}</dd>
            </>
          )}
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
  /** Undo cannot run; the page says why once, above the rows. */
  undoUnavailable: boolean;
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
                <Change
                  source={row.source}
                  before={row.current}
                  after={row.proposal}
                  afterLabel="Proposal"
                  applied={row.state === "applied"}
                />
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
                disabled={disabled || undoUnavailable}
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
  /** Undo cannot run; the page says why once, above the rows. */
  undoUnavailable: boolean;
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
                      before={row.current}
                      after={row.correction}
                      afterLabel="Correction"
                      applied={row.state === "applied"}
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
                    disabled={disabled || undoUnavailable}
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

/** Texts a source shows before its explicit Show all. */
const sourcePreview = 3;

/**
 * One file's or plugin's Japanese that was never translated: what it is,
 * whether players can reach it and why, then its first texts.
 */
function UntranslatedSource({ source }: { source: QaUntranslatedSource }) {
  const [expanded, setExpanded] = useState(false);
  const { title, kind } = qaSource(source);
  const listed = source.texts.length;
  return (
    <li>
      <span className="text-qa-source">
        <strong>{title}</strong>
        <small>
          {kind} · {source.count.toLocaleString()}
        </small>
      </span>
      {source.reach && (
        <p>
          <strong>
            {qaMayShow(source)
              ? "Players may see this."
              : "Players don't see this now."}
          </strong>{" "}
          {source.evidence}
        </p>
      )}
      <ul className="text-qa-texts">
        {(expanded ? source.texts : source.texts.slice(0, sourcePreview)).map(
          (row) => (
            <li key={row.pointer} lang="ja">
              {row.text}
            </li>
          ),
        )}
      </ul>
      {listed > sourcePreview && !expanded && (
        <Button variant="link" onClick={() => setExpanded(true)}>
          {listed < source.count
            ? `Show the first ${listed.toLocaleString()}`
            : `Show all ${listed.toLocaleString()}`}
        </Button>
      )}
      {expanded && listed < source.count && (
        <p className="muted">
          QA lists the first {listed.toLocaleString()} of{" "}
          {source.count.toLocaleString()}.
        </p>
      )}
    </li>
  );
}

/**
 * What QA did not cover: lines reviewers declined, which the user may read
 * and mark, and Japanese that was never translated.
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
        description="Lines no reviewer judged, and Japanese that was never translated."
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
                          <Change source={row.source} before={row.current} />
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
            {report.not_translated.length > 0 && (
              <section aria-label="Never translated">
                <h3>
                  Never translated ·{" "}
                  {report.not_translated
                    .reduce((total, source) => total + source.count, 0)
                    .toLocaleString()}
                </h3>
                <p className="muted">
                  QA reviews translations, so no reviewer read this Japanese and
                  QA did not correct it. Translate what players can see in its
                  own task.
                </p>
                <ul className="text-qa-untranslated">
                  {report.not_translated.map((source) => (
                    <UntranslatedSource
                      key={source.kind + source.file + (source.plugin || "")}
                      source={source}
                    />
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </DialogBody>
    </Modal>
  );
}
