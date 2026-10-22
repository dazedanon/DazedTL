import { useState } from "react";
import { api } from "../../api/client";
import type { TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { Feedback } from "../../ui/Feedback";
import { FieldRow } from "../../ui/FieldRow";
import { Notice } from "../../ui/Notice";
import { Section } from "../../ui/Section";
import {
  batchSummary,
  listedRun,
  priceRange,
  runMode,
  unconfirmedBatch,
} from "./apiRun";
import { OperationEntry, projectActivity } from "../guided/ActivityHistory";
import { LenRunInspector, type RunView } from "./LenRunInspector";

const money = (value: number) => "$" + value.toFixed(4);
/** Rows a run's request list shows before its explicit Show all. */
const listPreview = 10;
export function RequestsPanel({ state }: { state: TranslationState }) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const [path, setPath] = useState(".dazedtl/len-method/work/requests.json");
  const [inspecting, setInspecting] = useState<{
    run: string;
    index: number;
    view: RunView;
  }>({ run: "", index: 0, view: "requests" });
  const inspect = (run: string, index = 0, view: RunView = "requests") =>
    setInspecting({ run, index, view });
  // The operation compiling the plan; its run joins the list once saved.
  const [compiling, setCompiling] = useState("");
  const jobs = state.jobs.filter(
    (job) => job.kind === "translation" && listedRun(job),
  );
  // Start over and the other operations this game has run.
  const activity = projectActivity([], state.jobs);
  const inspected = jobs.find((job) => job.id === inspecting.run);
  // The run lists showing all their rows, as `${run}:${list}`.
  const [expanded, setExpanded] = useState<string[]>([]);
  const shown = <T,>(key: string, rows: T[]) =>
    expanded.includes(key) ? rows : rows.slice(0, listPreview);
  const showAll = (key: string, count: number) =>
    count > listPreview &&
    !expanded.includes(key) && (
      <Button
        variant="link"
        onClick={() => setExpanded((value) => [...value, key])}
      >
        Show all {count.toLocaleString()}
      </Button>
    );
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
                {runMode(job)} · {job.status.replaceAll("_", " ")}
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
                <Button onClick={() => inspect(job.id)}>Inspect run</Button>
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
            {!!job.batches.length &&
              (job.batches.some(unconfirmedBatch) ? (
                <Notice tone="warning">
                  Batches: {batchSummary(job.batches)}.{" "}
                  <Button
                    variant="link"
                    onClick={() => inspect(job.id, 0, "batches")}
                  >
                    {job.batches.filter(unconfirmedBatch).length === 1
                      ? "Attach its provider job"
                      : "Attach their provider jobs"}
                  </Button>
                </Notice>
              ) : (
                <p className="muted">Batches: {batchSummary(job.batches)}</p>
              ))}
            {!!job.issues.length && (
              <details>
                <summary>
                  {job.issues.length} request{" "}
                  {job.issues.length === 1 ? "error" : "errors"}
                </summary>
                <ActionList compact>
                  {shown(`${job.id}:issues`, job.issues).map((issue) => (
                    <ActionRow
                      key={issue.id}
                      title={issue.id}
                      description={issue.message}
                    >
                      <Button
                        variant="link"
                        onClick={() => inspect(job.id, issue.index)}
                      >
                        Inspect
                      </Button>
                    </ActionRow>
                  ))}
                </ActionList>
                {showAll(`${job.id}:issues`, job.issues.length)}
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
                <ActionList compact>
                  {shown(`${job.id}:notes`, job.qa_requests).map((request) => (
                    <ActionRow
                      key={request.id}
                      title={request.id}
                      description={`${request.notes} ${request.notes === 1 ? "note" : "notes"}`}
                    >
                      <Button
                        variant="link"
                        onClick={() => inspect(job.id, request.index)}
                      >
                        Inspect
                      </Button>
                    </ActionRow>
                  ))}
                </ActionList>
                {showAll(`${job.id}:notes`, job.qa_requests.length)}
              </details>
            )}
          </article>
        ))}
      </Section>
      {inspected && (
        <LenRunInspector
          key={`${inspected.id}:${inspecting.index}:${inspecting.view}`}
          projectId={state.projectId}
          job={inspected}
          initialIndex={inspecting.index}
          initialView={inspecting.view}
          active={state.active}
          onClose={() => inspect("")}
        />
      )}
      {!!activity.length && (
        <Section title="Other activity">
          <div className="guided-history">
            <ActionList compact>
              {activity.map((job) => (
                <ActionRow key={job.id} label={<OperationEntry job={job} />} />
              ))}
            </ActionList>
          </div>
        </Section>
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
