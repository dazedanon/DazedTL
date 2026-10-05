import type { Job, RunPayload } from "../../api/contracts";
import { ExpandableText } from "../../ui/ExpandableText";
import { RequestFailure } from "./RequestFailure";
import { requestStateLabel } from "./translationView";
import { displayText } from "../../ui/displayText";

const count = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString()
    : "Not recorded";

export function RequestTechnical({
  payload,
  job,
  compact = true,
  showModel = true,
  showStatus = true,
  showEstimate = true,
}: {
  payload: RunPayload;
  job: Job;
  compact?: boolean;
  showModel?: boolean;
  showStatus?: boolean;
  showEstimate?: boolean;
}) {
  const parameters = payload.parameters as Record<string, unknown> | null;
  const quote = job.approval?.detail || job.estimate;
  const usage = payload.usage;
  return (
    <div
      className={`request-technical request-technical--${compact ? "compact" : "fill"}`}
    >
      <div className="request-technical-summary">
        <section>
          <h3>This request</h3>
          <dl className="request-metrics">
            {showModel && (
              <div>
                <dt>Model</dt>
                <dd>
                  {displayText(parameters?.model) ||
                    job.model ||
                    "Not recorded"}
                </dd>
              </div>
            )}
            {showStatus && (
              <div>
                <dt>Status</dt>
                <dd>{requestStateLabel(payload.state)}</dd>
              </div>
            )}
            <div>
              <dt>Text entries</dt>
              <dd>
                {payload.source
                  ? Object.keys(payload.source).length.toLocaleString()
                  : "Not recorded"}
              </dd>
            </div>
          </dl>
          <RequestFailure payload={payload} />
        </section>
        {usage && (
          <section>
            <h3>Actual tokens</h3>
            <dl className="request-metrics">
              <div>
                <dt>Input</dt>
                <dd>{count(usage?.input_tokens)}</dd>
              </div>
              <div>
                <dt>Output</dt>
                <dd>{count(usage?.output_tokens)}</dd>
              </div>
              {usage?.total_tokens != null && (
                <div>
                  <dt>Total</dt>
                  <dd>{count(usage.total_tokens)}</dd>
                </div>
              )}
              {usage?.cache_read_input_tokens != null && (
                <div>
                  <dt>Cache reads</dt>
                  <dd>{count(usage.cache_read_input_tokens)}</dd>
                </div>
              )}
              {usage?.cache_creation_input_tokens != null && (
                <div>
                  <dt>Cache writes</dt>
                  <dd>{count(usage.cache_creation_input_tokens)}</dd>
                </div>
              )}
              {usage?.thinking_tokens != null && (
                <div>
                  <dt>Thinking</dt>
                  <dd>{count(usage.thinking_tokens)}</dd>
                </div>
              )}
            </dl>
          </section>
        )}
        {showEstimate && quote && (
          <section>
            <h3>Whole-run estimate</h3>
            <dl className="request-metrics">
              <div>
                <dt>Requests</dt>
                <dd>{count(quote.requests ?? quote.request_count)}</dd>
              </div>
              <div>
                <dt>Input tokens</dt>
                <dd>{count(quote.input_tokens)}</dd>
              </div>
              <div>
                <dt>Output tokens</dt>
                <dd>{count(quote.output_tokens)}</dd>
              </div>
            </dl>
          </section>
        )}
      </div>
      <section className="request-technical-payload">
        <h3>Exact API payload</h3>
        <ExpandableText
          text={JSON.stringify(payload.exact, null, 2) ?? "Not recorded"}
          label="API payload"
          truncate={compact}
          fill={!compact}
        />
      </section>
    </div>
  );
}
