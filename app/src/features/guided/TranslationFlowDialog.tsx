import { LoaderCircle } from "lucide-react";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { TranslationReviewContent } from "./TranslationReview";
import type { useTranslationFlow } from "./useTranslationFlow";

export function TranslationFlowDialog({ projectId, flow, approvalCurrent, inspect, remaining, otherFiles }: {
  projectId: string; flow: ReturnType<typeof useTranslationFlow>; approvalCurrent: boolean; inspect: (run?: string) => void;
  remaining: string[]; otherFiles: () => void;
}) {
  const value = flow.state;
  if (!value) return null;
  const loading = ["preparing", "estimating", "batch", "canceling"].includes(value.stage);
  const message = value.stage === "canceling" ? "Stopping preparation…" : value.stage === "batch" ? "Preparing the cost review…" : "Checking selected text and saved results…";
  return <Modal label="Translate selected text" className="guided-sheet translation-review translation-flow" dismissible={loading || !flow.busy} onDismiss={flow.cancel}>
    {value.stage === "review" ? <TranslationReviewContent projectId={projectId} job={value.job} preview={value.preview} busy={flow.busy}
      pendingKey={value.decision == null ? "" : `run:answer:${value.decision}`} disabled={flow.busy} approvalCurrent={approvalCurrent} error="" close={flow.cancel} answer={flow.answer} /> : <>
      <header className="guided-sheet-heading"><h2>{value.stage === "empty" ? "No new translation requests" : value.stage === "error" ? value.conflict ? "Saved work needs attention" : "Translation needs attention" : "Translation estimate"}</h2></header>
      <div className={`guided-sheet-body${loading ? " translation-flow-loading" : ""}`}>
        {loading ? <div role="status"><LoaderCircle size={22} className="job-status-spinner" aria-hidden="true" /><strong>{message}</strong><small>{value.files.length} selected {value.files.length === 1 ? "file" : "files"} · {value.mode === "batch" ? "Batch" : "Live"}</small></div>
          : value.stage === "empty" ? <p>All selected files were checked. No new API requests are needed.</p>
          : <><Message message={value.error || "Try preparing a fresh estimate."} />
            {value.conflict && <p>{remaining.length ? `${remaining.length} other selected ${remaining.length === 1 ? "file can" : "files can"} be checked now.` : "Open the saved run to check its status and recover any pending results."}</p>}</>}
      </div>
      <ActionBar feedback={null}>
        <Button disabled={value.stage === "canceling" || !loading && flow.busy} onClick={flow.cancel}>{loading ? "Cancel" : "Close"}</Button>
        {value.stage === "error" && <Button disabled={flow.busy} onClick={() => inspect(value.conflict?.matches[0]?.run || value.runId)}>View saved work</Button>}
        {value.stage === "error" && (value.conflict ? remaining.length > 0 && <Button variant="primary" disabled={flow.busy} onClick={otherFiles}>Translate other files</Button>
          : <Button variant="primary" disabled={flow.busy} onClick={flow.retry}>Try again</Button>)}
      </ActionBar>
    </>}
  </Modal>;
}
