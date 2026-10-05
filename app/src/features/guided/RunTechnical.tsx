import type { ReactNode } from "react";
import type { Job, NameTranslationPage } from "../../api/contracts";
import { ExpandableText } from "../../ui/ExpandableText";
import { NameTranslationFeedback } from "./NameTranslationFeedback";

/** Run evidence remains available even when no individual payload was retained. */
export function RunTechnical({
  job,
  readNames,
  actions,
}: {
  job: Job;
  readNames?: (offset: number) => Promise<NameTranslationPage>;
  actions?: ReactNode;
}) {
  const process = job.process!;
  const errors = [
    ...new Set(
      [
        ...(process.runErrors || process.errors),
        ...(process.monitoring &&
        ["error", "blocked", "save_error"].includes(process.monitoring.state)
          ? [process.monitoring.message]
          : []),
        ...(process.resultsUnavailable ? [process.resultsUnavailable] : []),
      ].filter(Boolean),
    ),
  ];
  if (
    !errors.length &&
    ["failed", "interrupted"].includes(job.status) &&
    job.message
  ) {
    errors.push(
      job.log?.length
        ? job.message
        : job.message.replace(" See the run log.", ""),
    );
  }
  const outputs = [
    job.availableOutputs?.length && `${job.availableOutputs.length} saved`,
    job.partialOutputs?.length && `${job.partialOutputs.length} partial`,
    process.appliedFiles && `${process.appliedFiles} applied`,
  ].filter(Boolean);
  const usage = Object.entries(process.usage || {}).filter(
    ([, count]) => count > 0,
  );
  return (
    <div className="run-technical">
      <section>
        <h3>Run record</h3>
        <p className="muted">
          {job.created && `${new Date(job.created).toLocaleString()} · `}
          <code>{job.id}</code>
        </p>
        <dl className="run-detail-summary">
          {!!job.files?.length && (
            <div>
              <dt>Files</dt>
              <dd>
                <ExpandableText
                  text={job.files.join(", ")}
                  label="Run files"
                  appearance="inline"
                />
              </dd>
            </div>
          )}
          {!!outputs.length && (
            <div>
              <dt>Outputs</dt>
              <dd>{outputs.join(" · ")}</dd>
            </div>
          )}
          {!!usage.length && (
            <div>
              <dt>Run usage</dt>
              <dd>
                {usage
                  .map(
                    ([key, count]) =>
                      `${count.toLocaleString()} ${key.replaceAll("_", " ")}`,
                  )
                  .join(" · ")}
              </dd>
            </div>
          )}
          {process.billing?.openrouter_cost != null && (
            <div>
              <dt>OpenRouter charge</dt>
              <dd>${process.billing.openrouter_cost.toFixed(5)}</dd>
            </div>
          )}
          {process.billing?.upstream_inference_cost != null && (
            <div>
              <dt>BYOK estimate</dt>
              <dd>
                ${process.billing.upstream_inference_cost.toFixed(5)} · billed
                separately by the host
              </dd>
            </div>
          )}
        </dl>
        {errors.map((error) => (
          <p className="translation-error" key={error}>
            {error}
          </p>
        ))}
        {!!process.uncertain && (
          <p className="muted">
            {process.uncertain}{" "}
            {process.uncertain === 1 ? "submission could" : "submissions could"}{" "}
            not be confirmed. No automatic retry was sent.
          </p>
        )}
        {!!process.duplicateSubmissions && (
          <p className="muted">
            {process.duplicateSubmissions} requests appear in multiple Batches.
          </p>
        )}
      </section>
      <NameTranslationFeedback value={job.nameTranslation} read={readNames} />
      {actions}
    </div>
  );
}

/** The worker's retained output tail, kept with run evidence instead of routine views. */
export function RunLog({ log }: { log?: string[] }) {
  if (!log?.length) return null;
  return (
    <section>
      <h3>Run log</h3>
      <ExpandableText text={log.join("\n")} label="Run log" tail />
    </section>
  );
}
