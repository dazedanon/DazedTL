import { useState } from "react";
import { api } from "../../api/client";
import type { TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Feedback } from "../../ui/Feedback";
import { FieldRow } from "../../ui/FieldRow";
import { Modal } from "../../ui/Modal";
import { Section } from "../../ui/Section";
import { listedRun, priceRange } from "./apiRun";
import { RequestInspector } from "./RequestInspector";

const money = (value: number) => "$" + value.toFixed(4);
export function RequestsPanel({ state }: { state: TranslationState }) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const [path, setPath] = useState(".dazedtl/len-method/work/requests.json");
  const [inspecting, setInspecting] = useState({ run: "", index: 0 });
  const [attach, setAttach] = useState({ run: "", index: 0, id: "" });
  const closeAttach = () => setAttach({ run: "", index: 0, id: "" });
  // The operation compiling the plan; its run joins the list once saved.
  const [compiling, setCompiling] = useState("");
  const jobs = state.jobs.filter(
    (job) => job.kind === "translation" && listedRun(job),
  );
  const inspected = jobs.find((job) => job.id === inspecting.run);
  // A run's actions report once, after its last button.
  const runActions = ["start", "stop", "discard", "cancel"];
  const runKey = (name: string, run: string) => `${name}:${run}`;
  const runAction = (name: string, run: string, task: () => Promise<unknown>) =>
    void action.run(task, "", runKey(name, run));
  return (
    <>
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
            {job.usage.openrouter_cost != null && (
              <p className="muted">
                OpenRouter charge collected: {money(job.usage.openrouter_cost)}
                {job.usage.upstream_inference_cost != null &&
                  ` · BYOK inference estimate: ${money(job.usage.upstream_inference_cost)} (billed separately by the host)`}
              </p>
            )}
            {job.quote && (
              <div className="translation-quote">
                <strong>
                  {priceRange(
                    money,
                    job.quote.cost,
                    job.mode === "batch"
                      ? job.quote.batch_cost_reused
                      : undefined,
                  )}{" "}
                  estimated · {job.quote.model}
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
                    " · Batch: " +
                      priceRange(
                        money,
                        job.quote.batch_cost,
                        job.quote.batch_cost_reused,
                      )}{" "}
                  · Rates: {job.quote.rates.source}
                </p>
                <small>{job.quote.basis}</small>
                {job.mode === "batch" &&
                  job.quote.provider === "openrouter" && (
                    <p className="muted">
                      OpenRouter uses a 24-hour window. Submitted Batches cannot
                      be canceled through this app; pausing stops local work and
                      future submissions.
                    </p>
                  )}
              </div>
            )}
            <div className="actions">
              {!!job.requests && (
                <Button
                  onClick={() => setInspecting({ run: job.id, index: 0 })}
                >
                  Inspect requests and results
                </Button>
              )}
              {job.mode !== "agent" &&
                (job.approved
                  ? !["complete", "uncertain"].includes(job.status)
                  : job.status === "ready") && (
                  <Button
                    variant="primary"
                    disabled={
                      action.busy || state.active || !state.providerEnabled
                    }
                    pending={
                      action.busy && action.key === runKey("start", job.id)
                    }
                    onClick={() =>
                      runAction("start", job.id, async () => {
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
                  pending={action.busy && action.key === runKey("stop", job.id)}
                  onClick={() =>
                    runAction("stop", job.id, () =>
                      api.translation.stop(state.projectId, job.id),
                    )
                  }
                >
                  {job.stop_requested
                    ? "Pause requested"
                    : "Pause at the next safe point"}
                </Button>
              )}
              {job.quote && !job.approved && job.status === "ready" && (
                <Button
                  disabled={action.busy}
                  pending={
                    action.busy && action.key === runKey("discard", job.id)
                  }
                  onClick={() =>
                    runAction("discard", job.id, () =>
                      api.translation.stop(state.projectId, job.id, true),
                    )
                  }
                >
                  Discard estimate
                </Button>
              )}
              {job.approved &&
                job.mode === "batch" &&
                job.can_cancel_provider !== false &&
                job.status !== "complete" && (
                  <Button
                    disabled={action.busy || job.cancel_requested}
                    pending={
                      action.busy && action.key === runKey("cancel", job.id)
                    }
                    onClick={() =>
                      runAction("cancel", job.id, () =>
                        api.translation.stop(state.projectId, job.id, true),
                      )
                    }
                  >
                    {job.cancel_requested
                      ? "Cancellation requested"
                      : "Cancel provider batch"}
                  </Button>
                )}
              {runActions.some((name) => action.key === runKey(name, job.id)) &&
                action.error && <Feedback error={action.error} />}
            </div>
            {!!job.batches.length && (
              <ul className="translation-batch-list">
                {job.batches.map((batch, index) => (
                  <li key={index}>
                    {batch.id ||
                      (batch.state === "submitting"
                        ? "Unconfirmed submission"
                        : "Not sent")}{" "}
                    · {batch.api_status || batch.state}
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
                <summary>
                  {job.issues.length} request{" "}
                  {job.issues.length === 1 ? "error" : "errors"}
                </summary>
                <ul>
                  {job.issues.map((issue) => (
                    <li key={issue.id}>
                      {issue.id}: {issue.message}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {!!job.qa_requests?.length && (
              <details>
                <summary>
                  {job.qa_requests.length === 1
                    ? "1 request has"
                    : `${job.qa_requests.length} requests have`}{" "}
                  source review notes
                </summary>
                <ul className="translation-batch-list">
                  {job.qa_requests.map((request) => (
                    <li key={request.id}>
                      {request.id} · {request.notes} notes{" "}
                      <Button
                        onClick={() =>
                          setInspecting({ run: job.id, index: request.index })
                        }
                      >
                        Inspect source notes
                      </Button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </article>
        ))}
      </Section>
      {attach.run && (
        <Modal
          label="Attach a provider job"
          size="sm"
          dismissible={!action.busy}
          onDismiss={closeAttach}
        >
          <DialogHeader title="Attach the matching provider job?" />
          <DialogBody>
            <p>
              Use the job ID from the provider for this exact submission.
              Collection will check its request IDs. This does not submit
              another batch.
            </p>
            <FieldRow id="attach-provider-job" label="Provider job ID" wide>
              {(props) => (
                <input
                  {...props}
                  value={attach.id}
                  onChange={(event) =>
                    setAttach({ ...attach, id: event.target.value })
                  }
                />
              )}
            </FieldRow>
          </DialogBody>
          <ActionBar
            feedback={
              action.key === "attach" &&
              action.error && <Feedback error={action.error} />
            }
          >
            <Button disabled={action.busy} onClick={closeAttach}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!attach.id.trim() || state.active}
              pending={action.busy && action.key === "attach"}
              onClick={() =>
                void action.run(
                  async () => {
                    await api.translation.attach(
                      state.projectId,
                      attach.run,
                      attach.index,
                      attach.id,
                    );
                    closeAttach();
                  },
                  "",
                  "attach",
                )
              }
            >
              Attach job
            </Button>
          </ActionBar>
        </Modal>
      )}
      {inspected && (
        <RequestInspector
          key={`${inspected.id}:${inspecting.index}`}
          projectId={state.projectId}
          job={inspected}
          initialIndex={inspecting.index}
          active={state.active}
          onClose={() => setInspecting({ run: "", index: 0 })}
        />
      )}
      <Section title="Request plan">
        <p className="muted">
          The starting prompt handles this automatically. You can also compile
          an engine adapter's saved plan here.
        </p>
        <FieldRow
          id="request-plan-path"
          label="Plan file, relative to the game"
          wide
        >
          {(props) => (
            <input
              {...props}
              value={path}
              onChange={(event) => setPath(event.target.value)}
            />
          )}
        </FieldRow>
        <div className="actions">
          <ActionControl
            label="Compile and review remaining work"
            disabled={state.active || action.busy || !path}
            pending={action.busy && action.key === "compile"}
            pendingText="Starting…"
            error={action.key === "compile" ? action.error : ""}
            job={state.jobs.find((job) => job.id === compiling)}
            onClick={() =>
              void action.run(
                async () => {
                  await flushDrafts();
                  const started = await api.translation.compile(
                    state.projectId,
                    path,
                  );
                  setCompiling(started.id);
                },
                "",
                "compile",
              )
            }
          />
        </div>
      </Section>
    </>
  );
}
