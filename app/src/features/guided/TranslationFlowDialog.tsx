import { CircleCheck, LoaderCircle } from "lucide-react";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { TranslationReviewContent } from "./TranslationReview";
import { flowLoading, type useTranslationFlow } from "./useTranslationFlow";
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
  if (!value) return null;
  const loading = flowLoading(value);
  const translatingNames =
    value.stage === "batch" &&
    value.namesApproved &&
    (!value.job?.nameTranslation ||
      value.job.nameTranslation.state === "running");
  const progress =
    value.stage === "estimating" && value.job?.id === value.estimateId
      ? value.job?.progress
      : undefined;
  const checked =
    progress &&
    Number.isSafeInteger(progress.current) &&
    Number.isSafeInteger(progress.total) &&
    progress.total > 0 &&
    progress.current > 0 &&
    progress.current <= progress.total
      ? progress
      : undefined;
  const mode = value.mode === "batch" ? "Batch" : "Live";
  const message =
    value.stage === "canceling"
      ? "Stopping preparation…"
      : translatingNames
        ? "Translating names and labels…"
        : value.stage === "batch"
          ? `Preparing the ${mode} cost review…`
          : value.stage === "estimating"
            ? checked && checked.current === checked.total
              ? "Finishing cost estimate…"
              : "Estimating translation cost…"
            : "Checking selected text and saved results…";
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
            {loading ? (
              <div className="translation-flow-progress">
                <div className="translation-flow-activity" role="status">
                  <LoaderCircle
                    size={22}
                    className="job-status-spinner"
                    aria-hidden="true"
                  />
                  <strong>{message}</strong>
                  <small>
                    {translatingNames
                      ? "Live · names and labels only"
                      : checked
                        ? `${checked.current} of ${checked.total} ${checked.total === 1 ? "file" : "files"} checked · ${mode}`
                        : `${value.files.length} selected ${value.files.length === 1 ? "file" : "files"} · ${mode}`}
                  </small>
                </div>
                {checked?.file && (
                  <div className="translation-flow-file">
                    <small>Last checked</small>
                    <ExpandableText
                      text={checked.file}
                      label="Last checked file"
                      appearance="inline"
                      limit={100}
                    />
                  </div>
                )}
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
          <ActionBar feedback={null}>
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
