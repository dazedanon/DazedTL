import { useState, type ReactNode } from "react";
import type { Job, Preview } from "../../api/contracts";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
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

/** Said wherever an estimate kept the approximate count of Claude input. */
export const approximateClaudeInput =
  "Claude's own token count was unavailable, so the input is approximate and likely low.";
/** Said wherever an estimate's model thinks, billed as output it can't predict. */
export const unestimatedThinking =
  "This model's thinking tokens are billed as output and are not included.";

/**
 * An estimate's cost in one mode, a range where reusing cached instructions
 * lowers it; undefined without a price.
 */
export function estimateCost(value: Record<string, unknown>, mode: string) {
  // A cached Batch costs least when every repeated instruction is reused and
  // most when none is; estimates saved before the maximum priced no reuse.
  const most = value.batch_max_cost ?? value.batch_nocache_cost;
  const costs = (
    mode === "batch"
      ? [value.batch_cached_cost, value.batch_cost, most]
      : [value.live_cost ?? value.estimated_cost]
  ).filter(numeric);
  if (!costs.length) return undefined;
  const low = Math.min(...costs),
    high = Math.max(...costs);
  return `$${low.toFixed(4)}${high > low ? `–$${high.toFixed(4)}` : ""}`;
}

export function TranslationCost({
  value,
  mode,
}: {
  value: Record<string, unknown>;
  mode: string;
}) {
  const batch = mode === "batch";
  const most = value.batch_max_cost ?? value.batch_nocache_cost;
  const caching =
    batch &&
    numeric(value.batch_cached_cost) &&
    numeric(most) &&
    most > value.batch_cached_cost;
  const prices = caching
    ? ([
        ["If repeated instructions are reused", value.batch_cached_cost],
        ["If none is reused", most],
      ] as const)
    : [];
  return (
    <section className="translation-cost-review" aria-label="Estimated cost">
      <div className="translation-cost-total">
        <span>Estimated {batch ? "Batch" : "Live"} cost</span>
        <strong>{estimateCost(value, mode) ?? "Price unavailable"}</strong>
        <small>
          {value.approximate_input === true && `${approximateClaudeInput} `}
          {value.unestimated_thinking_tokens === true &&
            `${unestimatedThinking} `}
          Final cost depends on actual usage.
        </small>
      </div>
      <dl className="translation-cost-tokens">
        {numeric(value.requests ?? value.request_count) && (
          <div>
            <dt>Requests</dt>
            <dd>{count(value.requests ?? value.request_count)}</dd>
          </div>
        )}
        <div>
          <dt>Input tokens</dt>
          <dd>{count(value.input_tokens)}</dd>
        </div>
        <div>
          <dt>Est. output tokens</dt>
          <dd>{count(value.output_tokens)}</dd>
        </div>
        {/* What the run sends, from its frozen settings (settings/effort). */}
        {typeof value.thinking_effort === "string" && (
          <div>
            <dt>Thinking effort</dt>
            <dd>{value.thinking_effort}</dd>
          </div>
        )}
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
      {caching && (
        <small className="translation-cache-note">
          The provider charges less for instructions it reuses, but a Batch
          sends its requests together, so it may reuse few of them.
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
  /** Leaves a pending approval for later; absent when closing would discard it. */
  later?: () => void;
  answer: (approved: boolean) => void;
  /** Chooses another model in place of the reviewed one's name. */
  model?: ReactNode;
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
      size="md"
      className="guided-sheet translation-review"
      dismissible={!props.busy && !!props.later}
      onDismiss={() => props.later?.()}
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
  later,
  answer,
  model,
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
      <DialogHeader title={title} />
      <DialogBody className="translation-review-body">
        <p className="translation-review-model">
          {model || job?.model || preview?.run?.model || "Saved model"}{" "}
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
        <ul className="translation-review-consequences">
          {!executionEnabled && (
            <li>
              Provider execution is off for this launch, so this review is for
              inspection only.
            </li>
          )}
          <li>
            {repeatSubmission
              ? `Earlier work may include this text; ${batch ? "submitting" : "starting"} again may charge for it twice.`
              : batch
                ? "Submitting sends paid API requests."
                : "Starting submits paid API requests."}
          </li>
          {(job?.temporary || preview) && (
            <li>
              Decline sends nothing, and Translate reuses this estimate until
              files or settings change.
            </li>
          )}
          <li>
            Results may replace working translations; earlier approved runs stay
            in History.
          </li>
          <li>Game files change only after Apply.</li>
        </ul>
      </DialogBody>
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
        {later && (
          <Button variant="quiet" disabled={busy} onClick={later}>
            Decide later
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
