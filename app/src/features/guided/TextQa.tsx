/** Text QA's questions for the user, its audit log and its coverage sheet. */

import { useEffect, useState } from "react";
import type { QaFinding, QaQuestion, QaReport } from "../../api/contracts";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";
import { StatusMark } from "../../ui/StatusMark";
import { StatusPanel } from "../../ui/StatusPanel";
import { qaGroups, qaOrigin } from "./qaView";

type Feedback = (
  key: string,
  pendingText?: string,
) => {
  feedbackKey: string;
  pending: boolean;
  pendingText: string;
  error: string;
  notice: string;
};

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
 * once; QA applies once every line has one.
 */
export function QaQuestions({
  questions,
  disabled,
  choose,
  feedback,
}: {
  questions: QaQuestion[];
  disabled: boolean;
  choose: (question: string, choice: "keep" | "use") => void;
  feedback: Feedback;
}) {
  const open = questions.filter((row) => !row.choice).length;
  return (
    <StatusPanel
      title="Needs you"
      state={open ? "needs_review" : "done"}
      progress={
        open
          ? `${open.toLocaleString()} of ${questions.length.toLocaleString()} to answer`
          : undefined
      }
      description="Reviewers could not settle these lines from the game's text. Choose for each; QA applies its corrections once every line has an answer."
    >
      {questions.map((row) => (
        <ActionRow
          key={row.id}
          label={
            <>
              <Change
                source={row.source}
                current={row.current}
                other={row.proposal}
                otherLabel="Proposal"
              />
              <small>{row.reason}</small>
              {row.places > 1 && <small>{row.places} places in the game</small>}
            </>
          }
        >
          {row.choice ? (
            <span className="text-qa-choice">
              {row.choice === "use" ? "Using the proposal" : "Keeping the text"}
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
    </StatusPanel>
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
                  <StatusMark state="skipped" />
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
  useEffect(() => {
    load().then(setReport, (reason: unknown) =>
      setError(reason instanceof Error ? reason.message : String(reason)),
    );
  }, [load]);
  const unreviewed = report?.not_reviewed.filter((row) => !row.reviewed) || [];
  return (
    <Modal label="What QA did not cover" onDismiss={onClose} size="lg">
      <DialogHeader
        title="What QA did not cover"
        description="Reviewers declined these lines, so no reviewer judged them, and QA cannot correct Japanese outside its inventory."
        onClose={onClose}
      />
      <DialogBody className="text-qa-coverage">
        {error && <Notice tone="warning">{error}</Notice>}
        {!report && !error && <p className="muted">Loading…</p>}
        {report && (
          <>
            <section aria-label="Not reviewed">
              <div className="check-results-heading">
                <h3>Not reviewed · {unreviewed.length.toLocaleString()}</h3>
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
              {report.not_reviewed.length ? (
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
              ) : (
                <Notice>Reviewers judged every line.</Notice>
              )}
            </section>
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
