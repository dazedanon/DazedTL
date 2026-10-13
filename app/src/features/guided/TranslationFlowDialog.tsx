import { CircleCheck, LoaderCircle } from "lucide-react";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { StepProgress } from "../../ui/StepProgress";
import {
  formatClock,
  formatDuration,
  formatRemaining,
} from "../../ui/workTime";
import { useRemaining, useSecond, useStepClock } from "../../state/useWorkTime";
import { TranslationReviewContent } from "./TranslationReview";
import { flowLoading, type useTranslationFlow } from "./useTranslationFlow";
import { estimateActivity } from "./estimateActivity";
import { NameTranslationFeedback } from "./NameTranslationFeedback";
import { api } from "../../api/client";
import { ExpandableText } from "../../ui/ExpandableText";

export function TranslationFlowDialog({
  projectId,
  flow,
  approvalCurrent,
  executionEnabled,
  inspect,
}: {
  projectId: string;
  flow: ReturnType<typeof useTranslationFlow>;
  approvalCurrent: boolean;
  executionEnabled: boolean;
  inspect: (run?: string) => void;
}) {
  const value = flow.state;
  const loading = !!value && flowLoading(value);
  const activity = value && loading ? estimateActivity(value) : undefined;
  const now = useSecond(loading);
  const clock = useStepClock(String(value?.started), activity?.current, now);
  // While stopping, the steps stay where the work stopped.
  const step = activity?.current ?? clock.last;
  const count = activity?.count;
  const remaining = useRemaining(count?.key ?? "", count, now);
  if (!value) return null;
  const translatingNames =
    value.stage === "batch" &&
    value.namesApproved &&
    (!value.job?.nameTranslation ||
      value.job.nameTranslation.state === "running");
  const mode = value.mode === "batch" ? "Batch" : "Live";
  const nameFeedback = value.stage !== "estimating" &&
    !translatingNames &&
    value.job?.nameTranslation && (
      <NameTranslationFeedback
        value={value.job.nameTranslation}
        read={(offset) =>
          api.guided.nameResults(projectId, value.job!.id, offset)
        }
      />
    );
  return (
    <Modal
      label="Translate selected text"
      size="md"
      className="guided-sheet translation-review translation-flow"
      dismissible={loading || !flow.busy}
      onDismiss={flow.cancel}
    >
      {value.stage === "review" ? (
        <TranslationReviewContent
          projectId={projectId}
          job={value.job}
          preview={value.preview}
          busy={flow.busy}
          pendingKey={
            value.decision == null ? "" : `run:answer:${value.decision}`
          }
          disabled={flow.busy}
          approvalCurrent={approvalCurrent}
          executionEnabled={executionEnabled}
          error=""
          answer={flow.answer}
        />
      ) : (
        <>
          <DialogHeader
            title={
              value.stage === "empty"
                ? "No new translation requests"
                : value.stage === "error"
                  ? value.runId
                    ? "Translation could not start"
                    : "Estimate could not finish"
                  : value.namesApproved
                    ? "Translation preparation"
                    : "Translation estimate"
            }
          />
          {/* The sheet keeps its size from start to finish, so a status or a
              short result sits in its centre. */}
          <DialogBody
            className={
              loading || value.stage === "empty"
                ? "translation-flow-centered"
                : undefined
            }
          >
            {loading && activity ? (
              <div className="translation-flow-progress">
                <div className="translation-flow-activity" role="status">
                  <LoaderCircle
                    size={22}
                    className="job-status-spinner"
                    aria-hidden="true"
                  />
                  <strong>{activity.title}</strong>
                  {/* Its line is kept while empty, so nothing moves when a
                      count appears. */}
                  <small className="translation-flow-count">
                    {count
                      ? `${count.current.toLocaleString()} of ${count.total.toLocaleString()} files` +
                        (remaining === undefined
                          ? ""
                          : ` · ${formatRemaining(remaining)}`)
                      : translatingNames
                        ? "Live · names and labels only"
                        : "\u00a0"}
                  </small>
                </div>
                <StepProgress
                  label="Estimate steps"
                  current={activity.steps.findIndex(({ id }) => id === step)}
                  steps={activity.steps.map(({ id, label }) => ({
                    id,
                    label,
                    // A finished step says how long it took, on a line every
                    // step keeps; the current one fills as far as its files
                    // have got.
                    detail:
                      id !== step && clock.spent(id) >= 500
                        ? formatDuration(clock.spent(id) / 1000)
                        : "\u00a0",
                    fraction: id === step ? activity.fraction : undefined,
                  }))}
                />
                <div
                  className="translation-flow-file"
                  data-empty={count?.file ? undefined : ""}
                >
                  <small>Last checked</small>
                  <ExpandableText
                    text={count?.file || "\u00a0"}
                    label="Last checked file"
                    appearance="inline"
                    limit={100}
                  />
                </div>
                {nameFeedback}
              </div>
            ) : value.stage === "empty" ? (
              <div className="translation-flow-progress">
                <div className="translation-flow-activity" role="status">
                  <CircleCheck
                    size={22}
                    className="translation-flow-done"
                    aria-hidden="true"
                  />
                  <p>
                    {value.namesApproved
                      ? "The name pass is finished. No file-text Batch requests are needed."
                      : "All selected files were checked. No new API requests are needed."}
                  </p>
                </div>
                {nameFeedback}
              </div>
            ) : (
              <Message
                message={value.error || "Try preparing a fresh estimate."}
              />
            )}
            {value.stage === "error" && nameFeedback}
          </DialogBody>
          <ActionBar
            feedback={
              loading && (
                <small className="translation-flow-elapsed">
                  {mode} · {value.files.length.toLocaleString()}{" "}
                  {value.files.length === 1 ? "file" : "files"} ·{" "}
                  {formatClock((now - value.started) / 1000)} elapsed
                </small>
              )
            }
          >
            <Button
              disabled={value.stage === "canceling" || (!loading && flow.busy)}
              onClick={flow.cancel}
            >
              {loading && !value.namesApproved ? "Cancel" : "Close"}
            </Button>
            {value.stage === "error" && (
              <Button disabled={flow.busy} onClick={() => inspect(value.runId)}>
                View saved work
              </Button>
            )}
            {value.stage === "error" && (
              <Button
                variant="primary"
                disabled={flow.busy}
                onClick={flow.retry}
              >
                Try again
              </Button>
            )}
          </ActionBar>
        </>
      )}
    </Modal>
  );
}
