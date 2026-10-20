/**
 * Text QA as both methods show it: where it stands, its questions for the
 * user and its audit log; and what it did not cover, for the inspector.
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
import { ExpandableText } from "../../ui/ExpandableText";
import { LineChange } from "../../ui/LineChange";
import { Notice } from "../../ui/Notice";
import { StatusMark } from "../../ui/StatusMark";
import { StepProgress } from "../../ui/StepProgress";
import type { QaStepDetails } from "./qaSteps";
import {
  qaActivity,
  qaCorrections,
  qaGroups,
  qaOrigin,
  qaPhase,
  qaReach,
  qaReviewedBefore,
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
  rerun = "Run QA again to check the text.",
  restorable = false,
  children,
  beside,
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
  /** How the user has an outdated or unreadable task checked again. */
  rerun?: string;
  /** History on the Project page can restore a whole batch. */
  restorable?: boolean;
  /** Fields before QA starts, such as its focus. */
  children?: ReactNode;
  /** Work that runs with QA, such as the playtest, right after its panel. */
  beside?: ReactNode;
}) {
  const phase = qaPhase(qa);
  // The game's plugins changed, as after the assistant's own fix, and the
  // assistant prepares QA again, keeping its review.
  const resuming = phase === "outdated" && !!qa.plugins_changed && waiting;
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
      : resuming
        ? "waiting"
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
            : resuming
              ? "The game's plugins changed during QA; your assistant prepares it again, which keeps the review done so far."
              : phase === "outdated"
                ? (qa.rules_changed
                    ? "An update changed QA's rules after this task was prepared. "
                    : qa.plugins_changed
                      ? "The game's plugins changed after QA. "
                      : "The game text changed after QA. ") + rerun
                : phase === "blocked"
                  ? `${qa.message} ${rerun}`
                  : phase === "running"
                    ? (qaReviewedBefore(qa)
                        ? "Your assistant is reviewing the text changed since earlier QA. "
                        : "Your assistant is reviewing. ") +
                      "Corrections apply on their own once they pass the editorial pass."
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
        {/* The stages show where review is; once it is over, the panel's
            summary and the rows below say what QA did. */}
        {phase === "running" && (
          <StepProgress label="QA stages" steps={qaStages(qa)} />
        )}
      </AssistantTask>
      {beside}
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
                <QaReason text={row.reason} />
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
                {!row.state && (
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
                <ActionControl
                  label="Use proposal"
                  disabled={disabled}
                  {...feedback("qa-use:" + row.id, "Saving…")}
                  onClick={() => choose(row.id, "use")}
                />
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
 * Characters of a reason shown before its explicit Show more: reviewers'
 * plain sentences fit, while a task made before they wrote one shows the
 * start of their full evidence.
 */
const reasonPreview = 140;

/** What is wrong with a line, in the reviewer's plain sentence. */
function QaReason({ text }: { text: string }) {
  return (
    <small>
      <ExpandableText
        text={text}
        label="Reason"
        appearance="inline"
        limit={reasonPreview}
      />
    </small>
  );
}
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
                    <QaReason text={row.reason} />
                    <small>
                      {[
                        qaOrigin(row),
                        row.files.join(", "),
                        row.places > 1 && `${row.places} places`,
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
  labels,
}: {
  rows: QaInterfaceText[];
  labels?: PluginLabel[];
}) {
  const stands = new Map(labels?.map((row) => [row.text, row]));
  const handed = (row: QaInterfaceText) => {
    const state = stands.get(row.text)?.state;
    return state && state !== "elsewhere" ? state : undefined;
  };
  return (
    <section aria-label="Too long for the screen">
      <h3>Too long for the screen · {rows.length.toLocaleString()}</h3>
      <p className="muted">
        {rows.some(handed)
          ? "The game squeezes or cuts off this text, which QA holds no line of. Plugin files shortens what comes from plugins."
          : "The game squeezes or cuts off this text, which QA holds no line of, such as a plugin's menu."}
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
                ? "In no plugin file"
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

/**
 * QA's record for the History inspector: defects no correction could fix,
 * reviewers' full notes, lines reviewers declined, Japanese never translated
 * and screen text QA can't correct. Each has its own owner, so the page leaves it out and the
 * inspector keeps the record.
 */
export function QaCoverageReport({
  load,
  labels,
}: {
  load: () => Promise<QaReport>;
  /** Guided's Plugin files labels; Assistant-led has no such task. */
  labels?: PluginLabel[];
}) {
  const [report, setReport] = useState<QaReport | null>(null);
  const [error, setError] = useState("");
  // The report is read once when the inspector opens, however often the
  // inspector around it renders.
  const first = useRef(load);
  useEffect(() => {
    first
      .current()
      .then(setReport, (reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
  }, []);
  if (error) return <Notice tone="warning">{error}</Notice>;
  if (!report) return null;
  const untranslated = report.not_translated.reduce(
    (total, source) => total + source.count,
    0,
  );
  return (
    <>
      {report.not_corrected.length > 0 && (
        <section aria-label="Not corrected">
          <h3>
            Not corrected · {report.not_corrected.length.toLocaleString()}
          </h3>
          <p className="muted">
            Reviewers found a problem in these lines, but no correction passed
            apply&apos;s checks, so they stay as they are.
          </p>
          <ActionList>
            {report.not_corrected.map((row) => (
              <ActionRow
                key={row.id}
                label={
                  <>
                    <Change source={row.source} before={row.current} />
                    <small>{row.reason}</small>
                    {row.evidence && <small>{row.evidence}</small>}
                    <small>
                      {row.places > 1
                        ? `${row.file} · ${row.places} places in the game`
                        : row.file}
                    </small>
                  </>
                }
              />
            ))}
          </ActionList>
        </section>
      )}
      {report.notes.length > 0 && (
        <section aria-label="Reviewers' notes">
          <h3>
            Reviewers&apos; notes · {report.notes.length.toLocaleString()}
          </h3>
          <p className="muted">
            The full reasoning behind the corrections and questions the page
            sums up in one sentence.
          </p>
          <ActionList>
            {report.notes.map((row) => (
              <ActionRow
                key={row.id}
                label={
                  <>
                    <strong>{row.current}</strong>
                    <small>{row.evidence}</small>
                    {row.editorial && <small>Editorial: {row.editorial}</small>}
                  </>
                }
              />
            ))}
          </ActionList>
        </section>
      )}
      {report.not_reviewed.length > 0 && (
        <section aria-label="Not reviewed">
          <h3>Not reviewed · {report.not_reviewed.length.toLocaleString()}</h3>
          <p className="muted">
            Reviewers declined these lines and no reviewer on another AI helper
            took them, so QA set them aside.
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
              />
            ))}
          </ActionList>
        </section>
      )}
      {untranslated > 0 && (
        <section aria-label="Never translated">
          <h3>Never translated · {untranslated.toLocaleString()}</h3>
          <p className="muted">
            QA reviews translations, so it did not read this Japanese. The
            playtest lists what players can see with the task that translates
            it.
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
        <ScreenLabels rows={report.interface_outside} labels={labels} />
      )}
    </>
  );
}
