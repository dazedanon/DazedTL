import { useState } from "react";
import { api } from "../../api/client";
import type {
  RequestPreview,
  TranslationJob,
  TranslationState,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import { Button } from "../../ui/Button";
import { Section } from "../../ui/Section";
import { Message } from "../../ui/Feedback";

const money = (value: number) => "$" + value.toFixed(4);
export function RequestsPanel({ state }: { state: TranslationState }) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const [path, setPath] = useState(".dazedtl/len-method/work/requests.json");
  const [preview, setPreview] = useState<RequestPreview | null>(null);
  const [reviewedRetry, setReviewedRetry] = useState(false);
  const [receipt, setReceipt] = useState("");
  const [attach, setAttach] = useState({ run: "", index: 0, id: "" });
  const jobs = state.jobs.filter((job) => job.kind === "translation");
  const inspect = (job: TranslationJob, index = 0) =>
    action.run(async () => {
      setPreview(await api.translation.request(state.projectId, job.id, index));
    });
  return (
    <>
      <Message message={action.error} onDismiss={action.clear} />
      <Section
        title="Translation runs"
        hint="Only saved, validated results count as translated"
      >
        {!jobs.length && (
          <p className="muted">
            The agent will prepare the source inventory and requests. They will
            appear here for inspection and API cost review.
          </p>
        )}
        {jobs.map((job) => (
          <article className="translation-run" key={job.id}>
            <div className="section-heading">
              <strong>
                {job.mode === "agent"
                  ? "Agent"
                  : job.mode === "batch"
                    ? "API Batch"
                    : "Live API"}{" "}
                · {job.status.replaceAll("_", " ")}
              </strong>
              <small>{new Date(job.updated).toLocaleString()}</small>
            </div>
            <p>{job.message}</p>
            <p>
              {job.accepted_units.toLocaleString()} /{" "}
              {job.units.toLocaleString()} units accepted · {job.requests}{" "}
              requests
            </p>
            {!!Object.keys(job.usage).length && (
              <p className="muted">
                Recorded usage: {(job.usage.input_tokens || 0).toLocaleString()}{" "}
                uncached input ·{" "}
                {(job.usage.output_tokens || 0).toLocaleString()} output ·{" "}
                {(job.usage.cache_read_input_tokens || 0).toLocaleString()}{" "}
                cached input tokens
              </p>
            )}
            {job.quote && (
              <div className="translation-quote">
                <strong>
                  {money(job.quote.cost)} estimated · {job.quote.model}
                </strong>
                <p>
                  {job.quote.requests} remaining requests ·{" "}
                  {job.quote.input_tokens.toLocaleString()} input /{" "}
                  {job.quote.output_tokens.toLocaleString()} estimated output
                  tokens
                </p>
                <p className="muted">
                  Live: {money(job.quote.live_cost)}
                  {job.quote.batch_cost !== null &&
                    " · Batch: " + money(job.quote.batch_cost)}{" "}
                  · Rates: {job.quote.rates.source}
                </p>
                <small>{job.quote.basis}</small>
              </div>
            )}
            <div className="actions">
              {!!job.requests && (
                <Button disabled={action.busy} onClick={() => inspect(job)}>
                  Inspect requests and results
                </Button>
              )}
              {job.mode !== "agent" &&
                !["complete", "uncertain"].includes(job.status) && (
                  <Button
                    variant="primary"
                    disabled={
                      action.busy || state.active || !state.providerEnabled
                    }
                    onClick={() =>
                      action.run(async () => {
                        await flushDrafts();
                        await api.translation.start(
                          state.projectId,
                          job.id,
                          job.approved ? "" : job.approval_token,
                        );
                      })
                    }
                  >
                    {job.approved
                      ? "Resume saved run"
                      : "Approve estimate and start"}
                  </Button>
                )}
              {["running", "waiting"].includes(job.status) && (
                <Button
                  disabled={action.busy || job.stop_requested}
                  onClick={() =>
                    action.run(() =>
                      api.translation.stop(state.projectId, job.id),
                    )
                  }
                >
                  {job.stop_requested
                    ? "Pause requested"
                    : "Pause at checkpoint"}
                </Button>
              )}
              {job.mode === "batch" && job.status !== "complete" && (
                <Button
                  disabled={action.busy || job.cancel_requested}
                  onClick={() =>
                    action.run(() =>
                      api.translation.stop(state.projectId, job.id, true),
                    )
                  }
                >
                  {job.cancel_requested
                    ? "Cancellation requested"
                    : "Cancel provider batch"}
                </Button>
              )}
            </div>
            {!!job.batches.length && (
              <ul className="translation-batch-list">
                {job.batches.map((batch, index) => (
                  <li key={index}>
                    {batch.id || "Unconfirmed submission"} ·{" "}
                    {batch.api_status || batch.state}
                    {(batch.state === "submitting" ||
                      batch.state === "unmatched") && (
                      <Button
                        onClick={() =>
                          setAttach({ run: job.id, index, id: "" })
                        }
                      >
                        Attach matching provider job
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {!!job.issues.length && (
              <details>
                <summary>{job.issues.length} requests need attention</summary>
                <ul>
                  {job.issues.map((issue) => (
                    <li key={issue.id}>
                      {issue.id}: {issue.message}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </article>
        ))}
      </Section>
      {attach.run && (
        <Section title="Reconcile an uncertain submission">
          <p>
            Use the job ID from the provider for this exact submission.
            Collection will check its request IDs. This does not submit another
            batch.
          </p>
          <label>
            Provider job ID
            <input
              value={attach.id}
              onChange={(event) =>
                setAttach({ ...attach, id: event.target.value })
              }
            />
          </label>
          <Button
            disabled={!attach.id.trim() || action.busy || state.active}
            onClick={() =>
              action.run(async () => {
                await api.translation.attach(
                  state.projectId,
                  attach.run,
                  attach.index,
                  attach.id,
                );
                setAttach({ run: "", index: 0, id: "" });
              })
            }
          >
            Attach job
          </Button>
        </Section>
      )}
      {preview && (
        <Section
          title={"Request " + (preview.index + 1) + " of " + preview.total}
          hint={preview.request.id}
        >
          <div className="actions">
            <Button
              disabled={preview.index === 0 || action.busy}
              onClick={() =>
                action.run(async () =>
                  setPreview(
                    await api.translation.request(
                      state.projectId,
                      preview.run_id,
                      preview.index - 1,
                    ),
                  ),
                )
              }
            >
              Previous
            </Button>
            <Button
              disabled={preview.index + 1 >= preview.total || action.busy}
              onClick={() =>
                action.run(async () =>
                  setPreview(
                    await api.translation.request(
                      state.projectId,
                      preview.run_id,
                      preview.index + 1,
                    ),
                  ),
                )
              }
            >
              Next
            </Button>
            <Button
              onClick={() =>
                action.run(() =>
                  window.dazedtl.copyText(JSON.stringify(preview, null, 2)),
                )
              }
            >
              Copy request
            </Button>
          </div>
          <div className="translation-table-wrap">
            <table className="translation-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Saved translation</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(preview.request.sources).map(([id, source]) => (
                  <tr key={id}>
                    <td>
                      <small>{id}</small>
                      <p>{source}</p>
                    </td>
                    <td>{preview.result?.translations[id] || "Pending"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>Exact compiled context and provider payload</summary>
            <pre className="translation-json">
              {JSON.stringify(preview.request, null, 2)}
            </pre>
          </details>
          {preview.result && (
            <Button
              disabled={state.active || action.busy}
              onClick={() =>
                action.run(async () => {
                  await api.translation.review(
                    state.projectId,
                    preview.run_id,
                    preview.request.id,
                    preview.request.fingerprint,
                  );
                  setPreview(
                    await api.translation.request(
                      state.projectId,
                      preview.run_id,
                      preview.index,
                    ),
                  );
                })
              }
            >
              {preview.result.reviewed
                ? "Source-checked review recorded"
                : "Mark this request source-checked"}
            </Button>
          )}
          {jobs
            .find((job) => job.id === preview.run_id && job.mode === "live")
            ?.issues.some(
              (issue) =>
                issue.id === preview.request.id && issue.state === "uncertain",
            ) && (
            <div className="translation-quote">
              <p>
                This request may already have been billed. Check the provider
                before allowing another attempt.
              </p>
              <label className="translation-check">
                <input
                  type="checkbox"
                  checked={reviewedRetry}
                  onChange={(event) => setReviewedRetry(event.target.checked)}
                />
                I reviewed the outcome and want to prepare a new quote for this
                request.
              </label>
              <Button
                disabled={!reviewedRetry || state.active || action.busy}
                onClick={() =>
                  action.run(async () => {
                    await api.translation.resolve(
                      state.projectId,
                      preview.run_id,
                      preview.request.id,
                      preview.request.fingerprint,
                    );
                    setReviewedRetry(false);
                  })
                }
              >
                Record review; allow a new quote
              </Button>
            </div>
          )}
          <details>
            <summary>
              {preview.result
                ? "Import a reviewed correction"
                : "Import a saved result receipt"}
            </summary>
            {preview.result && (
              <p className="footnote">
                Include this result hash as replaces_sha256 in the receipt:{" "}
                {preview.result.result_sha256}. The previous result is retained
                and affected QA becomes pending.
              </p>
            )}
            <label>
              Receipt file, relative to the game
              <input
                value={receipt}
                onChange={(event) => setReceipt(event.target.value)}
              />
            </label>
            <Button
              disabled={!receipt || state.active || action.busy}
              onClick={() =>
                action.run(async () => {
                  await api.translation.accept(
                    state.projectId,
                    preview.run_id,
                    preview.request.id,
                    receipt,
                  );
                  setPreview(
                    await api.translation.request(
                      state.projectId,
                      preview.run_id,
                      preview.index,
                    ),
                  );
                })
              }
            >
              Validate and save result
            </Button>
          </details>
        </Section>
      )}
      <Section title="Request plan">
        <p className="muted">
          The starting prompt handles this automatically. You can also compile
          an engine adapter's saved plan here.
        </p>
        <label>
          Plan file, relative to the game
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
          />
        </label>
        <Button
          disabled={state.active || action.busy || !path}
          onClick={() =>
            action.run(async () => {
              await flushDrafts();
              await api.translation.compile(state.projectId, path);
            })
          }
        >
          Compile and review remaining work
        </Button>
      </Section>
    </>
  );
}
