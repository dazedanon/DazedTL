/**
 * Text QA as both methods show it: where it stands, its questions for the
 * user, its audit log and its coverage sheet.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  PluginLabel,
  QaFinding,
  QaInterfaceText,
  QaQuestion,
  QaReport,
  QaState,
  QaUntranslatedSource,
} from "../../api/contracts";
import type { DisplayState } from "../../ui/displayStatus";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { AssistantTask, type AssistantTaskState } from "../../ui/AssistantTask";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { LineChange } from "../../ui/LineChange";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";
import { StatusMark } from "../../ui/StatusMark";
import { StepProgress } from "../../ui/StepProgress";
import type { QaStepDetails } from "./qaSteps";
import {
  qaActivity,
  qaCorrections,
  qaGroups,
  qaInterface,
  qaNotTranslated,
  qaOrigin,
  qaPhase,
  qaReach,
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
    name: "undo" | "reapply" | "choose",
    details: QaStepDetails,
    success?: string,
  ) => void;
  onCoverage: () => void;
  /** Opens the task's report, where the page has an inspector. */
  report?: ReactNode;
  /** How the user has an outdated or unreadable task checked again. */
  rerun?: string;
  /** History on the Project page can restore a whole batch. */
  restorable?: boolean;
  /** Fields before QA starts, such as its focus. */
  children?: ReactNode;
}) {
  const phase = qaPhase(qa);
  const coverage = qa.coverage;
  const notTranslated = qa.not_translated;
  const interfaceNote = qaInterface(qa.interface);
  // Once applied, only a proposal the user chose went into the game.
  const questions = qa.applied
    ? qa.questions.filter((row) => row.choice === "use")
    : qa.questions;
  // Corrections in the game; with every one undone, QA reads as done.
  const { applied, undone } = qaCorrections(qa);
  // New QA rules leave applied corrections without Undo, and undone ones
  // without Apply again; the page says so once, above the rows.
  const unavailable = !!qa.rules_changed && applied + undone > 0;
  const state: AssistantTaskState =
    phase === "applied"
      ? applied
        ? "applied"
        : "done"
      : phase === "outdated" || phase === "blocked"
        ? phase
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
  const reapply = (id: string) =>
    run("qa-reapply:" + id, "reapply", { findings: [id] }, "Applied again.");
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
              : phase === "blocked"
                ? `${qa.message} ${rerun}`
                : phase === "running"
                  ? "Your assistant is reviewing. Corrections apply on their own once they pass the editorial pass."
                  : phase === "questions"
                    ? "QA applies its corrections once you answer the questions below."
                    : phase === "ready"
                      ? "Your assistant applies these corrections next; you can also apply them here."
                      : qaSummary(qa)
        }
        help={
          "Verified corrections go into the game as one text batch, saved as a version. Undo puts back one correction and Apply again redoes it" +
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
              (coverage?.not_reviewed || notTranslated || interfaceNote) ? (
                <>
                  {[
                    // The summary that describes finished QA counts them.
                    coverage &&
                      !["applied", "clean"].includes(phase) &&
                      `${(coverage.lines - coverage.not_reviewed).toLocaleString()} lines checked`,
                    coverage?.not_reviewed &&
                      `${coverage.not_reviewed.toLocaleString()} not reviewed (declined by the reviewer)`,
                    notTranslated && qaNotTranslated(notTranslated),
                    interfaceNote,
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
      {unavailable && (
        <Notice>
          An update changed QA's rules after these corrections were applied, so{" "}
          {applied && undone
            ? "Undo and Apply again are"
            : applied
              ? "Undo is"
              : "Apply again is"}{" "}
          no longer available. {rerun}
        </Notice>
      )}
      {questions.length > 0 && phase !== "outdated" && (
        <QaQuestions
          questions={questions}
          disabled={disabled}
          unavailable={unavailable}
          feedback={feedback}
          choose={(question, choice) =>
            run(`qa-${choice}:` + question, "choose", { question, choice })
          }
          undo={undo}
          reapply={reapply}
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
          unavailable={unavailable}
          feedback={feedback}
          undo={undo}
          reapply={reapply}
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
  const japanese = { label: "Japanese", text: source, lang: "ja" };
  return (
    <LineChange
      rows={
        applied && after !== undefined
          ? [
              japanese,
              { label: "Now", text: after, change: "added" },
              { label: "Was", text: before, change: "removed" },
            ]
          : [
              japanese,
              { label: "Now", text: before },
              ...(after === undefined
                ? []
                : [{ label: afterLabel, text: after }]),
            ]
      }
    />
  );
}

/**
 * Undo for an applied correction, and Apply again for an undone one; each
 * runs as a text batch of its own and saves a version.
 */
function AppliedControl({
  row,
  disabled,
  unavailable,
  feedback,
  undo,
  reapply,
}: {
  row: { id: string; state?: "applied" | "undone" };
  disabled: boolean;
  /** Neither can run; the page says why once, above the rows. */
  unavailable: boolean;
  feedback: Feedback;
  undo: (id: string) => void;
  reapply: (id: string) => void;
}) {
  if (row.state === "applied")
    return (
      <ActionControl
        label="Undo"
        variant="link"
        disabled={disabled || unavailable}
        {...feedback("qa-undo:" + row.id, "Undoing…")}
        onClick={() => undo(row.id)}
      />
    );
  return (
    <>
      <span className="text-qa-choice">Undone</span>
      <ActionControl
        label="Apply again"
        variant="link"
        disabled={disabled || unavailable}
        {...feedback("qa-reapply:" + row.id, "Applying…")}
        onClick={() => reapply(row.id)}
      />
    </>
  );
}

/**
 * The lines QA cannot settle from the game's text. Each choice saves at
 * once; QA applies once every line has one, and an applied proposal can be
 * undone and applied again like a correction.
 */
export function QaQuestions({
  questions,
  disabled,
  unavailable,
  choose,
  undo,
  reapply,
  feedback,
}: {
  questions: QaQuestion[];
  disabled: boolean;
  /** Undo and Apply again cannot run; the page says why once, above the rows. */
  unavailable: boolean;
  choose: (question: string, choice: "keep" | "use") => void;
  undo: (id: string) => void;
  reapply: (id: string) => void;
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
            {row.state ? (
              <AppliedControl
                row={row}
                disabled={disabled}
                unavailable={unavailable}
                feedback={feedback}
                undo={undo}
                reapply={reapply}
              />
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
/** Lines a scene correction shows before its explicit Show all. */
const scenePreview = 3;

/**
 * What a correction changes, or each line of a scene correction, which
 * applies and undoes as one; an applied one reads as a diff.
 */
function FindingChange({ row }: { row: QaFinding }) {
  const [all, setAll] = useState(false);
  const change = (
    line: Pick<QaFinding, "source" | "current" | "correction">,
    key?: number,
  ) => (
    <Change
      key={key}
      source={line.source}
      before={line.current}
      after={line.correction}
      afterLabel="Correction"
      applied={row.state === "applied"}
    />
  );
  if (!row.lines) return change(row);
  const lines = all ? row.lines : row.lines.slice(0, scenePreview);
  return (
    <div className="text-qa-scene">
      {lines.map((line, index) => change(line, index))}
      {lines.length < row.lines.length && (
        <Button variant="link" onClick={() => setAll(true)}>
          Show all {row.lines.length.toLocaleString()} lines
        </Button>
      )}
    </div>
  );
}

/**
 * Every correction, by category: what the line said, what it says now, why,
 * and Undo for an applied one or Apply again for one undone. A long category
 * shows its first rows until the user asks for the rest.
 */
export function QaAuditLog({
  findings,
  disabled,
  unavailable,
  undo,
  reapply,
  feedback,
}: {
  findings: QaFinding[];
  disabled: boolean;
  /** Undo and Apply again cannot run; the page says why once, above the rows. */
  unavailable: boolean;
  undo: (id: string) => void;
  reapply: (id: string) => void;
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
                    <FindingChange row={row} />
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
                {row.state && (
                  <AppliedControl
                    row={row}
                    disabled={disabled}
                    unavailable={unavailable}
                    feedback={feedback}
                    undo={undo}
                    reapply={reapply}
                  />
                )}
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
          <strong>{qaReach(source)}</strong> {source.evidence}
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

/** A label's state in Plugin files, in the words every screen shares. */
const pluginLabelStates: Record<
  Exclude<PluginLabel["state"], "elsewhere">,
  DisplayState
> = {
  waiting: "not_started",
  ready: "ready",
  applied: "applied",
  // The assistant settled it by keeping it, with its reason beside it.
  kept: "done",
};

/**
 * Text the game squeezes or cuts off that QA holds no line of. In Guided,
 * Plugin files shortens what comes from plugin files, so each label says
 * where it stands there.
 */
function ScreenLabels({
  rows,
  plugins,
}: {
  rows: QaInterfaceText[];
  plugins?: QaPluginLabels;
}) {
  const stands = new Map(plugins?.labels.map((row) => [row.text, row]));
  const handed = (row: QaInterfaceText) => {
    const state = stands.get(row.text)?.state;
    return state && state !== "elsewhere" ? state : undefined;
  };
  const open = rows.some((row) =>
    ["waiting", "ready"].includes(handed(row) || ""),
  );
  return (
    <section aria-label="Too long for the screen">
      <div className="check-results-heading">
        <h3>Too long for the screen · {rows.length.toLocaleString()}</h3>
        {plugins && open && (
          <Button variant="link" onClick={plugins.open}>
            Open Plugin files
          </Button>
        )}
      </div>
      <p className="muted">
        {rows.some(handed)
          ? "The game squeezes or cuts off this text, which QA doesn't correct. Plugin files' assistant shortens what comes from plugins when you copy that task, and you apply it there."
          : "The game squeezes or cuts off this text, but it comes from outside the data QA corrects, such as a plugin's menu. Shorten it in its own task, such as Plugin files."}
      </p>
      <ActionList>
        {rows.map((row) => {
          const label = stands.get(row.text);
          const state = handed(row);
          // The mark says where a handed label stands; only a kept one adds
          // why, and one Plugin files can't find where it goes instead.
          const note =
            label?.state === "kept"
              ? `Kept as it is: ${label.reason || ""}`
              : label?.state === "elsewhere"
                ? "In no plugin file; shorten it in its own task"
                : "";
          return (
            <ActionRow
              key={row.text + row.title}
              title={row.text}
              description={[row.title, note].filter(Boolean).join(" · ")}
            >
              {state && <StatusMark state={pluginLabelStates[state]} />}
            </ActionRow>
          );
        })}
      </ActionList>
    </section>
  );
}

/** Where Guided's Plugin files task stands on each squeezed label. */
export type QaPluginLabels = { labels: PluginLabel[]; open: () => void };

/**
 * What QA did not cover: lines reviewers declined, which the user may read
 * and mark, Japanese that was never translated, and text too long for the
 * screen that QA holds no line of.
 */
export function QaCoverage({
  load,
  markReviewed,
  onClose,
  plugins,
}: {
  load: () => Promise<QaReport>;
  markReviewed: (identities: string[]) => Promise<QaReport>;
  onClose: () => void;
  /** Guided's Plugin files labels; Assistant-led has no such task. */
  plugins?: QaPluginLabels;
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
        description="Lines no reviewer judged, Japanese that was never translated, and screen text QA can't correct."
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
            {report.interface_error && (
              <section aria-label="Interface screens">
                <h3>Interface screens</h3>
                <p className="muted">
                  {`DazedTL couldn't run the game to capture its screens, so QA reviewed its text without them. ${report.interface_error}`}
                </p>
              </section>
            )}
            {report.interface_outside.length > 0 && (
              <ScreenLabels rows={report.interface_outside} plugins={plugins} />
            )}
            {report.interface_unreviewed.length > 0 && (
              <section aria-label="Squeezed after QA">
                <h3>
                  Squeezed after QA ·{" "}
                  {report.interface_unreviewed.length.toLocaleString()}
                </h3>
                <p className="muted">
                  Plugin files changed after QA finished, and the game now
                  squeezes or cuts off these lines. QA reviews them when it runs
                  on changed game text.
                </p>
                <ActionList>
                  {report.interface_unreviewed.map((row) => (
                    <ActionRow
                      key={row.text + row.title}
                      title={row.text}
                      description={row.title}
                    />
                  ))}
                </ActionList>
              </section>
            )}
          </>
        )}
      </DialogBody>
    </Modal>
  );
}
