import { LoaderCircle } from "lucide-react";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { TranslationReviewContent } from "./TranslationReview";
import type { useTranslationFlow } from "./useTranslationFlow";
import { NameTranslationFeedback } from "./NameTranslationFeedback";
import { api } from "../../api/client";
import { ExpandableText } from "../../ui/ExpandableText";

export function TranslationFlowDialog({ projectId, flow, approvalCurrent, inspect }: {
  projectId: string; flow: ReturnType<typeof useTranslationFlow>; approvalCurrent: boolean; inspect: (run?: string) => void;
}) {
  const value = flow.state;
  if (!value) return null;
  const loading = ["preparing", "estimating", "batch", "canceling"].includes(value.stage);
  const translatingNames = value.stage === "batch" && value.namesApproved && (!value.job?.nameTranslation || value.job.nameTranslation.state === "running");
  const progress = value.stage === "estimating" && value.job?.id === value.estimateId ? value.job?.progress : undefined;
  const checked = progress && Number.isSafeInteger(progress.current) && Number.isSafeInteger(progress.total)
    && progress.total > 0 && progress.current > 0 && progress.current <= progress.total ? progress : undefined;
  const mode = value.mode === "batch" ? "Batch" : "Live";
  const message = value.stage === "canceling" ? "Stopping preparation…"
    : translatingNames ? "Translating names and labels…"
    : value.stage === "batch" ? `Preparing the ${mode} cost review…`
    : value.stage === "estimating" ? checked && checked.current === checked.total ? "Finishing cost estimate…" : "Estimating translation cost…"
    : "Checking selected text and saved results…";
  const nameFeedback = value.stage !== "estimating" && !translatingNames && value.job?.nameTranslation && <NameTranslationFeedback value={value.job.nameTranslation} read={offset => api.guided.nameResults(projectId, value.job!.id, offset)} />;
  return <Modal label="Translate selected text" className="guided-sheet translation-review translation-flow" dismissible={loading || !flow.busy} onDismiss={flow.cancel}>
    {value.stage === "review" ? <TranslationReviewContent projectId={projectId} job={value.job} preview={value.preview} busy={flow.busy}
      pendingKey={value.decision == null ? "" : `run:answer:${value.decision}`} disabled={flow.busy} approvalCurrent={approvalCurrent} error="" close={flow.cancel} answer={flow.answer} /> : <>
      <header className="guided-sheet-heading"><h2>{value.stage === "empty" ? "No new translation requests" : value.stage === "error" ? "Translation needs attention" : value.namesApproved ? "Translation preparation" : "Translation estimate"}</h2></header>
      <div className={`guided-sheet-body${loading ? " translation-flow-loading" : ""}`}>
        {loading ? <div className="translation-flow-progress"><div className="translation-flow-activity" role="status"><LoaderCircle size={22} className="job-status-spinner" aria-hidden="true" /><strong>{message}</strong><small>{translatingNames ? "Live · names and labels only" : checked ? `${checked.current} of ${checked.total} ${checked.total === 1 ? "file" : "files"} checked · ${mode}` : `${value.files.length} selected ${value.files.length === 1 ? "file" : "files"} · ${mode}`}</small></div>
          {checked?.file && <div className="translation-flow-file"><small>Last checked</small><ExpandableText text={checked.file} label="Last checked file" appearance="inline" limit={100} /></div>}
          {nameFeedback}</div>
          : value.stage === "empty" ? <p>{value.namesApproved ? "The name pass is finished. No file-text Batch requests are needed." : "All selected files were checked. No new API requests are needed."}</p>
          : <Message message={value.error || "Try preparing a fresh estimate."} />}
        {!loading && nameFeedback}
      </div>
      <ActionBar feedback={null}>
        <Button disabled={value.stage === "canceling" || !loading && flow.busy} onClick={flow.cancel}>{loading && !value.namesApproved ? "Cancel" : "Close"}</Button>
        {value.stage === "error" && <Button disabled={flow.busy} onClick={() => inspect(value.runId)}>View saved work</Button>}
        {value.stage === "error" && <Button variant="primary" disabled={flow.busy} onClick={flow.retry}>Try again</Button>}
      </ActionBar>
    </>}
  </Modal>;
}
