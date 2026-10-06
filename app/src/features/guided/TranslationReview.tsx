import { useState } from "react";
import { X } from "lucide-react";
import type { Job, Preview } from "../../api/contracts";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { VirtualList } from "../../ui/VirtualList";
import { PreparedRequestPreview } from "./PreparedRequestPreview";
import { NameTranslationFeedback } from "./NameTranslationFeedback";
import { api } from "../../api/client";

const numeric = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const count = (value: unknown) =>
  numeric(value) ? value.toLocaleString() : "-";
const pathKey = (path: string) => path;

export function TranslationCost({
  value,
  mode,
}: {
  value: Record<string, unknown>;
  mode: string;
}) {
  const batch = mode === "batch";
  const costs = (
    batch
      ? [value.batch_nocache_cost, value.batch_cached_cost, value.batch_cost]
      : [value.live_cost ?? value.estimated_cost]
  ).filter(numeric);
  const low = Math.min(...costs),
    high = Math.max(...costs);
  const writes =
    numeric(value.cache_write_tokens) && value.cache_write_tokens > 0;
  const reads = numeric(value.cache_read_tokens) && value.cache_read_tokens > 0;
  const caching =
    writes ||
    reads ||
    (numeric(value.batch_cached_cost) &&
      value.batch_cached_cost !== value.batch_nocache_cost);
  const prices =
    batch && caching
      ? ([
          ["Without prompt caching", value.batch_nocache_cost],
          ["With prompt caching (estimated)", value.batch_cached_cost],
        ] as const)
      : [];
  return (
    <section className="translation-cost-review" aria-label="Estimated cost">
      <div className="translation-cost-total">
        <span>Estimated {batch ? "Batch" : "Live"} cost</span>
        <strong>
          {costs.length
            ? `$${low.toFixed(4)}${high > low ? `–$${high.toFixed(4)}` : ""}`
            : "Price unavailable"}
        </strong>
        <small>Final cost depends on actual usage.</small>
      </div>
      <dl className="translation-cost-tokens">
        <div>
          <dt>Requests</dt>
          <dd>{count(value.requests ?? value.request_count)}</dd>
        </div>
        <div>
          <dt>Input tokens</dt>
          <dd>{count(value.input_tokens)}</dd>
        </div>
        <div>
          <dt>Est. output tokens</dt>
          <dd>{count(value.output_tokens)}</dd>
        </div>
      </dl>
      {prices.some(([, price]) => numeric(price)) && (
        <dl className="translation-cost-prices">
          {prices
            .filter(([, price]) => numeric(price))
            .map(([label, price]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>${Number(price).toFixed(5)}</dd>
              </div>
            ))}
        </dl>
      )}
      {batch && caching && (
        <small className="translation-cache-note">
          The provider can reuse repeated instructions at a lower rate. This
          estimate includes creating the cache; actual savings vary.
          {writes && !reads && " No reuse is assumed for this batch."}
        </small>
      )}
    </section>
  );
}

type ReviewProps = {
  projectId: string;
  job?: Job;
  preview?: Preview;
  busy: boolean;
  pendingKey: string;
  disabled: boolean;
  approvalCurrent: boolean;
  /** False when this launch cannot contact providers; review stays inspectable. */
  executionEnabled: boolean;
  error: string;
  close: () => void;
  answer: (approved: boolean) => void;
};
export function TranslationReview(props: ReviewProps & { job: Job }) {
  if (!props.job.approval) return null;
  return (
    <Modal
      label={
        props.job.approval.kind === "batch"
          ? "Review Batch submission"
          : "Review names and labels"
      }
      className="guided-sheet translation-review"
      dismissible={!props.busy}
      onDismiss={props.close}
    >
      <TranslationReviewContent {...props} />
    </Modal>
  );
}
export function TranslationReviewContent({
  projectId,
  job,
  preview,
  busy,
  pendingKey,
  disabled,
  approvalCurrent,
  executionEnabled,
  error,
  close,
  answer,
}: ReviewProps) {
  const [inspecting, setInspecting] = useState(false);
  const detail: Record<string, unknown> | undefined =
    job?.approval?.detail || preview?.estimate?.value;
  if (!detail) return null;
  const batch = !preview && job?.approval?.kind === "batch",
    files = job?.files || preview?.paths || [];
  // Only estimates built from the request queue keep their exact requests;
  // connections without Batch support estimate from token counts.
  const requestRun = batch
    ? job?.id
    : preview?.estimate?.value.basis === "request_queue"
      ? preview.estimate.jobId
      : undefined;
  const speakerReview = !preview && job?.approval?.kind === "speakers";
  const speakersBeforeBatch = speakerReview && job?.mode === "batch";
  const repeatSubmission =
    preview?.estimate?.repeatSubmission || job?.repeatSubmission;
  const speakers = Array.isArray(detail.speakers)
    ? detail.speakers.map(String)
    : [];
  const title = preview
    ? "Review Live translation"
    : batch
      ? "Review Batch submission"
      : "Review names and labels";
  return (
    <>
      <header className="guided-sheet-heading translation-review-heading">
        <h2>{title}</h2>
        <Button
          variant="quiet"
          disabled={busy}
          aria-label="Close review"
          onClick={close}
        >
          <X size={18} aria-hidden="true" />
        </Button>
      </header>
      <div className="guided-sheet-body translation-review-body">
        <p className="translation-review-model">
          {job?.model || preview?.run?.model || "Saved model"}{" "}
          <span>
            ·{" "}
            {batch
              ? "Batch"
              : speakerReview
                ? "Live · names and labels only"
                : "Live"}
          </span>
        </p>
        {speakersBeforeBatch && (
          <p className="translation-review-notice">
            Translate these names and labels with Live first. File text remains
            on Batch and receives its own cost review afterward.
          </p>
        )}
        <TranslationCost value={detail} mode={batch ? "batch" : "translate"} />
        {batch && detail.provider === "openrouter" && (
          <p className="translation-review-notice">
            OpenRouter uses a 24-hour completion window. Submitted Batches
            cannot be canceled through this app. Prices exclude any separate
            BYOK fees.
          </p>
        )}
        <section
          className="translation-review-scope"
          aria-label="Prepared scope"
        >
          <h3>
            {speakerReview && "Names and labels from "}
            {files.length} selected {files.length === 1 ? "file" : "files"}
          </h3>
          {files.length <= 8 ? (
            <ul className="guided-preview-paths">
              {files.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          ) : (
            <div className="guided-preview-files">
              <VirtualList
                items={files}
                itemKey={pathKey}
                label="Selected files"
                empty={null}
              >
                {(name) => <div className="guided-preview-path">{name}</div>}
              </VirtualList>
            </div>
          )}
          {!!speakers.length && (
            <p className="translation-review-speakers">
              <strong>Names and labels to translate</strong>
              <br />
              {speakers.join(", ")}
            </p>
          )}
        </section>
        {batch && job && (
          <NameTranslationFeedback
            value={job.nameTranslation}
            read={(offset) => api.guided.nameResults(projectId, job.id, offset)}
          />
        )}
        <p className="translation-review-notice">
          {!executionEnabled &&
            "Provider execution is disabled for this launch, so this review is for inspection only. "}
          {repeatSubmission
            ? "Earlier work may include this text. Starting again may incur duplicate API charges. "
            : "Submitting incurs API charges. "}
          {(job?.temporary || preview) && "Decline discards this preparation. "}
          Results may replace working translations; earlier approved runs stay
          in History. Game files change only after Apply.
        </p>
      </div>
      <ActionBar feedback={<Message message={error} />}>
        {requestRun && (
          <Button
            variant="quiet"
            disabled={busy}
            onClick={() => setInspecting(true)}
          >
            Preview request
          </Button>
        )}
        <Button
          pending={busy && pendingKey === "run:answer:false"}
          disabled={disabled}
          onClick={() => answer(false)}
        >
          Decline
        </Button>
        <Button
          variant="primary"
          pending={busy && pendingKey === "run:answer:true"}
          disabled={disabled || !approvalCurrent || !executionEnabled}
          onClick={() => answer(true)}
        >
          {preview
            ? "Start Live translation"
            : batch
              ? "Submit Batch"
              : "Translate names (Live)"}
        </Button>
      </ActionBar>
      {inspecting && requestRun && (
        <PreparedRequestPreview
          key={`${projectId}:${requestRun}`}
          projectId={projectId}
          runId={requestRun}
          estimate={!!preview}
          close={() => setInspecting(false)}
        />
      )}
    </>
  );
}
