import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronRight, LoaderCircle } from "lucide-react";
import type {
  Job,
  NameTranslationPage,
  RequestPage,
  RunPayload,
} from "../../api/contracts";
import { Button } from "../../ui/Button";
import { ComboBox } from "../../ui/ComboBox";
import { Message } from "../../ui/Feedback";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { ProtectedText, RequestSource } from "./RequestSource";
import { RequestTechnical } from "./RequestTechnical";
import { ExpandableText } from "../../ui/ExpandableText";
import { historyOutcome } from "./historyView";
import { activeRun, requestAttempt, translatedLines } from "./translationView";
import {
  requestOutcome,
  requestBatches,
  requestBatchOutcome,
  requestRows,
  payloadForBatch,
  type RequestBatch,
} from "./requestView";
import { RunLog, RunTechnical } from "./RunTechnical";
import { RequestFailure } from "./RequestFailure";
import { providerBatchActive } from "./batchView";
import { InspectedFile } from "./InspectedFile";
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";

const formatted = (value: unknown) =>
  typeof value === "string" ? value : JSON.stringify(value, null, 2);
function responseText(response: unknown) {
  const body =
    response && typeof response === "object" && "text" in response
      ? response.text ||
        ("refusal" in response && typeof response.refusal === "string"
          ? response.refusal
          : null) ||
        response
      : response;
  if (typeof body !== "string") return formatted(body);
  try {
    return formatted(JSON.parse(body));
  } catch {
    return body;
  }
}
const tabs = [
  { id: "source", label: "Source" },
  { id: "response", label: "Response" },
  { id: "json", label: "Technical" },
] as const;
type Tab = (typeof tabs)[number]["id"] | "file";
type InspectorView = { index: number; tab: Tab; batch: string | null };
export type RequestInspectionTarget = {
  file: string;
  /** Lines still left in a Database files or Maps & events file; the
      inspector opens on them. */
  left?: number;
  index?: number;
  validation?: boolean;
};
const inspectorKey = (id: string) => "dazedtl:request-view:" + id;
/** A Live request still at the provider after its run ended has no
    confirmed outcome. */
const unconfirmed = (
  job: Job,
  row: { state: string; providerFinished?: boolean },
) =>
  row.state === "uncertain" ||
  (job.mode !== "batch" &&
    !activeRun(job) &&
    row.state === "submitted" &&
    !row.providerFinished);
/** The request to read first: an unconfirmed submission, then a failed or
    rejected one. The observed attention rows hold each kind's first request
    at its latest attempt, so a later attempt that passed settles it. */
function issueRequest(job: Job) {
  const requests = job.process?.attention || [];
  return (
    requests.find((row) => unconfirmed(job, row)) ||
    requests.find((row) => ["failed", "rejected"].includes(row.state))
  );
}
/** Without a named group, the request page opens the first group holding it. */
function issueView(job: Job): InspectorView {
  const issue = issueRequest(job);
  return issue
    ? { index: issue.index, tab: "response", batch: null }
    : { index: 0, tab: "source", batch: null };
}
/** The last view of this run, or none so it opens on what needs attention. */
function savedView(id: string): InspectorView | null {
  const fallback = null;
  try {
    const value = JSON.parse(localStorage.getItem(inspectorKey(id)) || "null");
    if (value && ["run", "log"].includes(value.tab)) value.tab = "json";
    if (value?.batch === "run-details") value.batch = null;
    if (
      !value ||
      !Number.isSafeInteger(value.index) ||
      value.index < 0 ||
      (value.tab !== "file" && !tabs.some((tab) => tab.id === value.tab))
    )
      return fallback;
    return {
      index: value.index,
      tab: value.tab,
      batch: typeof value.batch === "string" ? value.batch : null,
    };
  } catch {
    return fallback;
  }
}
export function runLabel(job: Job) {
  return `${job.logicalPhase === "database" ? "Database" : job.logicalPhase === "dialogue" ? "Maps & events" : job.logicalPhase === "advanced" ? "Other event text" : job.logicalPhase === "variables" ? "Comparisons" : job.logicalPhase === "speakers" ? "Speakers" : "Translation"} · ${job.mode === "batch" ? "Batch" : job.mode === "estimate" ? "Estimate" : "Live"}`;
}
type Props = {
  job: Job;
  readPayload?: (index: number) => Promise<RunPayload>;
  readRequests?: (
    group: string | null,
    index: number | null,
  ) => Promise<RequestPage>;
  initialRequest?: RequestInspectionTarget;
  readNames?: (offset: number) => Promise<NameTranslationPage>;
  compact?: boolean;
  actions?: ReactNode;
  projectId?: string;
  batchActions?: (batch?: RequestBatch) => ReactNode;
};
export function ProcessPanel(props: Props) {
  return props.job.process ? (
    <RequestProcess
      key={`${props.job.id}:${props.initialRequest?.file || ""}:${props.initialRequest?.index ?? ""}:${!!props.initialRequest?.validation}`}
      {...props}
    />
  ) : null;
}
function RequestProcess({
  job,
  readPayload,
  readRequests,
  readNames,
  initialRequest,
  actions,
  batchActions,
  projectId,
}: Props) {
  const process = job.process!;
  const [view, setView] = useState<InspectorView>(() =>
    initialRequest
      ? {
          index: initialRequest.index ?? -1,
          tab: initialRequest.validation
            ? process.rejected
              ? "response"
              : "json"
            : initialRequest.left
              ? "file"
              : "source",
          batch: initialRequest.index == null ? "file" : null,
        }
      : savedView(job.id) || issueView(job),
  );
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [attemptSelection, setAttemptSelection] = useState<{
    request: number;
    attempt: number;
  } | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [fileOpened, setFileOpened] = useState<string>();
  const [unlinkedFile, setUnlinkedFile] = useState(initialRequest?.file);
  const reader = useRef<HTMLDivElement>(null);
  const tabId = useId();
  const attemptTabId = useId();
  const batches = process.batches || [];
  const groups = requestBatches(process);
  // A Batch run opened on a file without a linked request selects no group.
  const fileOnly = job.mode === "batch" && view.batch === "file";
  const group = view.batch === "file" ? null : view.batch;
  // Requests arrive a page at a time. Choosing within the loaded page keeps
  // it; another page, group or receipt revision reads again, and the loaded
  // page stays visible while a receipt revision refreshes it.
  const [loaded, setLoaded] = useState<{
    group: string | null;
    anchor: number | null;
    page: RequestPage;
  } | null>(null);
  const holds =
    !!loaded &&
    loaded.group === group &&
    view.index >= 0 &&
    loaded.page.rows.some((row) => row.indices.includes(view.index));
  const anchor = holds ? loaded.anchor : view.index >= 0 ? view.index : null;
  const pageRead = useRead(
    readRequests && !fileOnly
      ? JSON.stringify([group, anchor, process.requestRevision || ""])
      : null,
    () => readRequests!(group, anchor),
  );
  useOnChange(pageRead.value, (value) => {
    if (value) setLoaded({ group, anchor, page: value });
  });
  const pageError =
    pageRead.error === undefined
      ? ""
      : pageRead.error instanceof Error
        ? pageRead.error.message
        : "Saved requests unavailable.";
  const page =
    !fileOnly && loaded?.group === group && loaded.anchor === anchor
      ? loaded.page
      : null;
  // The page names the group that holds the request; until it arrives, the
  // view's own group stays selected.
  const selectedBatch = fileOnly
    ? undefined
    : groups.find((batch) =>
        page
          ? batch.id === page.group
          : batch.id === view.batch || batch.batches.includes(view.batch || ""),
      ) || (job.mode === "batch" ? undefined : groups[0]);
  const selectedProviders = selectedBatch?.provider
    ? [selectedBatch.provider, ...selectedBatch.clarifications]
    : [];
  const requests =
    page && page.group === selectedBatch?.id ? requestRows(page.rows) : [];
  // Paging stays in place while another page of the same group loads.
  const pages =
    page ||
    (loaded && loaded.page.group === selectedBatch?.id ? loaded.page : null);
  const pageLoading = pageRead.pending && !page;
  const selected =
    view.index < 0
      ? undefined
      : requests.find((row) => row.indices.includes(view.index)) || requests[0];
  const index = selected?.index;
  // Follow the shared observer's receipt changes, including a clarification
  // that changes provider state without changing the grouped request state.
  const receiptRevision = JSON.stringify([
    selected?.indices,
    selected?.state,
    selected?.providerFinished,
    selectedProviders.map((batch) => [batch.id, batch.status]),
  ]);
  function change(value: Partial<InspectorView>) {
    setView((previous) => {
      const next = { ...previous, ...value };
      try {
        localStorage.setItem(inspectorKey(job.id), JSON.stringify(next));
      } catch {
        /* Evidence remains backend-owned. */
      }
      return next;
    });
  }
  const payloadRead = useRead(
    index == null || !readPayload ? null : `${index}:${receiptRevision}`,
    () => readPayload!(index!),
  );
  // The request stays visible while receipt changes refresh it.
  useOnChange(payloadRead.value, (value) => {
    if (value) setPayload(value);
  });
  const busy = payloadRead.pending || (pageLoading && view.index >= 0);
  const error =
    payloadRead.error === undefined
      ? ""
      : payloadRead.error instanceof Error
        ? payloadRead.error.message
        : "Saved request unavailable.";
  useOnChange(busy, (now) => {
    if (!now) setRetrying(false);
  });
  const requestPayload =
    payload && payload.index === index
      ? payloadForBatch(
          payload,
          selectedProviders.length
            ? selectedProviders.map((batch) => batch.id)
            : undefined,
        )
      : null;
  const attempts = requestPayload?.responseAttempts || [];
  const retries = attempts.filter((attempt) => attempt.kind === "retry");
  const attemptIndex = Math.max(
    0,
    Math.min(
      attempts.length - 1,
      attemptSelection && attemptSelection.request === index
        ? attemptSelection.attempt
        : attempts.length - 1,
    ),
  );
  const visiblePayload =
    requestPayload && requestAttempt(requestPayload, attemptIndex);
  useEffect(() => {
    reader.current?.scrollTo(0, 0);
  }, [index, view.tab, attemptIndex]);
  const choose = (number: number) => change({ index: number });
  function openBatch(batch: RequestBatch) {
    setAttemptSelection(null);
    change({ batch: batch.id, index: batch.first ?? 0, tab: "source" });
  }
  const outcomeOf = (
    row: { state: string; providerFinished?: boolean },
    outcome: ReturnType<typeof requestOutcome>,
  ) =>
    unconfirmed(job, row)
      ? ({ group: "pending", label: "Submission unconfirmed" } as const)
      : outcome;
  const selectionOutcome =
    selected &&
    (visiblePayload
      ? outcomeOf(
          {
            state: visiblePayload.state,
            providerFinished: selected.providerFinished,
          },
          requestOutcome({
            ...visiblePayload,
            providerFinished: selected.providerFinished,
          }),
        )
      : outcomeOf(selected, selected.outcome));
  const atProvider =
    (visiblePayload?.state || selected?.state) === "submitted" &&
    !selected?.providerFinished &&
    (job.mode === "batch"
      ? selectedProviders.some((batch) => providerBatchActive(batch.status))
      : activeRun(job));
  const translated = visiblePayload && translatedLines(visiblePayload);
  const comparison = translated && (
    <table className="translation-comparison">
      <thead>
        <tr>
          <th>Original</th>
          <th>Translation</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(visiblePayload.source!).map(([key, text]) => (
          <tr key={key}>
            <td>
              <small>{key}</small>
              <ProtectedText text={text} />
            </td>
            <td>
              <ProtectedText text={translated[key]} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  // A request holding several files' lines, such as map display names, stays
  // on the file it was opened from.
  const selectedFile =
    selected && !(unlinkedFile && selected.files?.[unlinkedFile])
      ? selected.file
      : unlinkedFile;
  // The run's frozen event text sources, or the comparison review it used.
  const sourcesLabel =
    job.logicalPhase === "variables"
      ? "Comparison review"
      : "Event text sources";
  const contentTabs =
    projectId && selectedFile
      ? [...tabs, { id: "file" as const, label: "File contents" }]
      : tabs;
  const contentTab =
    view.tab === "file" && !(projectId && selectedFile) ? "source" : view.tab;
  // The file reader stays mounted after its tab opens, keeping search and paging.
  if (contentTab === "file" && fileOpened !== (selectedFile || undefined))
    setFileOpened(selectedFile || undefined);
  const legacyIssues = (process.validationIssues || []).filter(
    (issue) =>
      (!selectedFile || issue.file === selectedFile) &&
      !process.files?.[issue.file]?.states.includes("rejected"),
  );
  const issue = issueRequest(job);
  return (
    <div className="translation-process" data-view={view.tab}>
      <div className="process-overview">
        <div>
          <strong>{runLabel(job)}</strong>
          <ExpandableText
            text={job.model || "Model not recorded"}
            label="Run model"
            appearance="inline"
            limit={100}
          />
          {!!job.files?.length && (
            <span className="muted">
              {job.files.length} {job.files.length === 1 ? "file" : "files"}
            </span>
          )}
          {job.mode !== "batch" && (
            <span className="badge">{historyOutcome(job).label}</span>
          )}
        </div>
        {(issue || !!process.validationIssues?.length) && (
          <Button
            variant="quiet"
            onClick={() => {
              setUnlinkedFile(
                issue?.file || process.validationIssues?.[0].file,
              );
              setAttemptSelection(null);
              change(
                issue
                  ? issueView(job)
                  : { index: -1, tab: "json", batch: "file" },
              );
            }}
          >
            Review issues
          </Button>
        )}
      </div>
      <div
        className={`request-workspace${job.mode === "batch" ? "" : " request-workspace--single"}`}
      >
        {job.mode === "batch" && (
          <aside
            className="request-batch-list"
            aria-label="Batches in this run"
          >
            {groups.length ? (
              <ul className="request-batch-items">
                {groups.map((batch) => {
                  const outcome = requestBatchOutcome(batch, job);
                  const count = batch.provider
                    ? batch.provider.total
                    : batch.total;
                  const clarificationCount = batch.clarifications.every(
                    (child) => child.total != null,
                  )
                    ? batch.clarifications.reduce(
                        (sum, child) => sum + child.total!,
                        0,
                      )
                    : undefined;
                  return (
                    <li key={batch.id}>
                      <button
                        type="button"
                        className="request-batch-row"
                        aria-label={`Select ${batch.label}`}
                        aria-current={
                          selectedBatch?.id === batch.id ? "true" : undefined
                        }
                        onClick={() => openBatch(batch)}
                      >
                        <span className="request-batch-summary">
                          <span>
                            <strong>{batch.label}</strong>
                            {count != null && count > 0 && (
                              <span className="muted">
                                {count.toLocaleString()}{" "}
                                {count === 1 ? "request" : "requests"}
                              </span>
                            )}
                          </span>
                          {outcome && (
                            <span
                              className="request-outcome"
                              data-state={
                                outcome.failed
                                  ? "failed"
                                  : outcome.successful
                                    ? "finished"
                                    : "pending"
                              }
                            >
                              {outcome.label}
                            </span>
                          )}
                          {outcome &&
                            outcome.summary !==
                              `${count?.toLocaleString()} requests` &&
                            outcome.summary !==
                              `${count?.toLocaleString()} request` && (
                              <small>{outcome.summary}</small>
                            )}
                          {!!batch.clarifications.length &&
                            !outcome?.clarification && (
                              <small>
                                {clarificationCount
                                  ? `${clarificationCount.toLocaleString()} clarification ${clarificationCount === 1 ? "request" : "requests"}`
                                  : "Includes clarification"}
                              </small>
                            )}
                          {!!batch.files && (
                            <small>
                              {batch.files}{" "}
                              {batch.files === 1 ? "file" : "files"}
                            </small>
                          )}
                        </span>
                        <ChevronRight size={16} aria-hidden="true" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="muted">No batches or saved requests yet.</p>
            )}
            {batchActions?.(selectedBatch)}
          </aside>
        )}
        <section
          className="payload-inspector request-batch-reader"
          aria-label="Request details"
        >
          <div className="request-selection">
            <div className="request-selection-summary">
              {selectedBatch && job.mode === "batch" && (
                <strong>{selectedBatch.label}</strong>
              )}
              <div className="request-picker">
                <ComboBox
                  key={selectedBatch?.id || "requests"}
                  selectionOnly
                  aria-label="Choose request"
                  value={index == null ? "" : String(index)}
                  placeholder={
                    pageLoading ? "Reading requests…" : "No requests"
                  }
                  disabled={!requests.length}
                  options={requests.map((row, position) => {
                    const outcome = outcomeOf(row, row.outcome);
                    const number = page!.offset + position + 1;
                    const label = `Request ${number.toLocaleString()} of ${page!.total.toLocaleString()}`;
                    return {
                      value: String(row.index),
                      label,
                      // Typed numbers match with or without separators.
                      searchText: `${label}\nRequest ${number}\n${outcome.label}`,
                      description: outcome.label,
                      tone:
                        outcome.group === "failed"
                          ? ("error" as const)
                          : unconfirmed(job, row)
                            ? ("warning" as const)
                            : undefined,
                    };
                  })}
                  onChange={(value) => choose(Number(value))}
                />
              </div>
              {pages && (pages.previous != null || pages.next != null) && (
                <div className="request-pages">
                  <Button
                    variant="quiet"
                    disabled={pageRead.pending || pages.previous == null}
                    onClick={() =>
                      change({ batch: pages.group, index: pages.previous! })
                    }
                  >
                    Previous
                  </Button>
                  <Button
                    variant="quiet"
                    disabled={pageRead.pending || pages.next == null}
                    onClick={() =>
                      change({ batch: pages.group, index: pages.next! })
                    }
                  >
                    Next
                  </Button>
                </div>
              )}
              {selectionOutcome && contentTab !== "file" && (
                <span
                  className="request-outcome"
                  data-state={selectionOutcome.group}
                  role="status"
                >
                  {atProvider && (
                    <LoaderCircle
                      size={14}
                      className="job-status-spinner"
                      aria-hidden="true"
                    />
                  )}
                  {selectionOutcome.label}
                </span>
              )}
            </div>
          </div>
          <Tabs
            id={tabId}
            label="Request content"
            items={contentTabs}
            value={contentTab}
            onChange={(tab) => change({ tab })}
          />
          {contentTab !== "file" && attempts.length > 1 && (
            <Tabs
              id={attemptTabId}
              label="Request attempt"
              value={String(attemptIndex)}
              items={attempts.map((attempt, index) => ({
                id: String(index),
                label:
                  attempt.kind === "original"
                    ? "Original"
                    : attempt.kind === "clarification"
                      ? "Clarification retry"
                      : retries.length > 1
                        ? `Retry ${retries.indexOf(attempt) + 1}`
                        : "Retry",
              }))}
              onChange={(attempt) =>
                setAttemptSelection({
                  request: index!,
                  attempt: Number(attempt),
                })
              }
            />
          )}
          {projectId && selectedFile && (
            <div
              className="file-preview-panel"
              hidden={contentTab !== "file"}
              role="tabpanel"
              id={`${tabId}-panel-file`}
              aria-labelledby={`${tabId}-tab-file`}
            >
              {fileOpened === selectedFile && (
                <InspectedFile
                  key={selectedFile}
                  projectId={projectId}
                  file={selectedFile}
                  left={
                    selectedFile === initialRequest?.file
                      ? initialRequest.left
                      : undefined
                  }
                />
              )}
            </div>
          )}
          <div
            className="request-reader"
            hidden={contentTab === "file"}
            ref={reader}
            tabIndex={0}
            aria-label="Saved request content"
            aria-busy={busy}
            role={attempts.length > 1 ? "tabpanel" : undefined}
            id={
              attempts.length > 1
                ? `${attemptTabId}-panel-${attemptIndex}`
                : undefined
            }
            aria-labelledby={
              attempts.length > 1
                ? `${attemptTabId}-tab-${attemptIndex}`
                : undefined
            }
          >
            <Message message={pageError} />
            {pageError && (
              <Button
                variant="quiet"
                disabled={pageRead.pending}
                onClick={pageRead.retry}
              >
                Retry reading requests
              </Button>
            )}
            <Message message={error} />
            {(error || retrying) && readPayload && (
              <Button
                variant="quiet"
                pending={retrying}
                disabled={busy}
                onClick={() => {
                  setRetrying(true);
                  payloadRead.retry();
                }}
              >
                {retrying ? "Reading request…" : "Retry reading request"}
              </Button>
            )}
            {selectedFile && (
              <div className="request-selection-file muted">
                <ExpandableText
                  text={selectedFile}
                  label="Selected file"
                  appearance="inline"
                  limit={80}
                />
              </div>
            )}
            {view.tab !== "source" &&
              legacyIssues.map((issue) => (
                <p className="translation-error" key={issue.file}>
                  {issue.file}: validation mismatches were recorded, but this
                  older run did not retain which request failed.
                </p>
              ))}
            {visiblePayload?.unused && (
              <div className="request-unused">
                <p className="muted">
                  This extra choice response was not used. The saved file uses
                  the validated responses below.
                </p>
                <div className="request-references">
                  {visiblePayload.unused.appliedRequests.map((index) => (
                    <Button
                      key={index}
                      variant="quiet"
                      onClick={() => choose(index)}
                    >
                      View used request {index + 1}
                    </Button>
                  ))}
                </div>
              </div>
            )}
            <TabPanel
              id={tabId}
              value={contentTab === "file" ? "source" : contentTab}
            >
              {view.tab === "json" ? (
                <div className="request-technical-content">
                  <RunTechnical
                    job={job}
                    readNames={readNames}
                    actions={actions}
                  />
                  {!!batches.length && (
                    <section>
                      <h3>Batch receipts</h3>
                      {(selectedProviders.length
                        ? selectedProviders
                        : batches
                      ).map((batch) => (
                        <div className="process-receipt" key={batch.id}>
                          <p>
                            <code>{batch.id}</code> · {batch.status}
                          </p>
                          {(batch.errors || []).map((error, index) => (
                            <div className="translation-error" key={index}>
                              <p>
                                {error.message ||
                                  "The provider did not record an error message."}
                              </p>
                              {[
                                error.code,
                                error.param,
                                error.custom_id,
                              ].filter(Boolean).length > 0 && (
                                <small>
                                  {[error.code, error.param, error.custom_id]
                                    .filter(Boolean)
                                    .join(" · ")}
                                </small>
                              )}
                            </div>
                          ))}
                        </div>
                      ))}
                    </section>
                  )}
                  {visiblePayload && (
                    <RequestTechnical
                      key={`${visiblePayload.index}:${attemptIndex}`}
                      payload={visiblePayload}
                      job={job}
                      showModel={false}
                      showStatus={false}
                      showEstimate={false}
                    />
                  )}
                  {job.estimate && (
                    <section>
                      <h3>Saved estimate</h3>
                      <ExpandableText
                        text={formatted(job.estimate)}
                        label="Saved estimate"
                      />
                    </section>
                  )}
                  {job.eventTextReview && (
                    <section>
                      <h3>{sourcesLabel}</h3>
                      <ExpandableText
                        text={formatted(job.eventTextReview)}
                        label={sourcesLabel}
                      />
                    </section>
                  )}
                  <RunLog log={job.log} />
                </div>
              ) : initialRequest && view.index < 0 ? (
                <p className="muted">
                  {process.noRequestFiles?.includes(initialRequest.file)
                    ? "This file produced no new requests in this pass."
                    : "No saved request is linked to this file in this attempt."}{" "}
                  File contents shows its current text.
                </p>
              ) : selectedBatch?.provider && !selectedBatch.total ? (
                <p className="muted">
                  The saved receipt does not identify this batch’s requests.
                  Technical contains the retained receipts and failure details.
                </p>
              ) : view.tab === "response" ? (
                <>
                  {visiblePayload && (
                    <RequestFailure payload={visiblePayload} details />
                  )}
                  {visiblePayload?.responseOrigin === "validated" && (
                    <p className="muted">
                      Previously saved translation. The original provider
                      response was not retained.
                    </p>
                  )}
                  {visiblePayload?.responseOrigin === "log" && (
                    <p className="muted">
                      Final attempt recovered from the saved validation log.
                      Earlier retry bodies were not retained.
                    </p>
                  )}
                  {!visiblePayload ? (
                    error || retrying ? null : (
                      <p className="muted">
                        {busy
                          ? "Reading saved request…"
                          : "No request response is available. Technical contains any retained failure details."}
                      </p>
                    )
                  ) : comparison ? (
                    comparison
                  ) : visiblePayload.response != null ? (
                    <>
                      {["failed", "rejected"].includes(
                        visiblePayload.state,
                      ) && <small className="muted">Provider reply</small>}
                      <pre>{responseText(visiblePayload.response)}</pre>
                    </>
                  ) : visiblePayload.error != null ? null : (
                    <p className="muted" role="status">
                      {selected?.providerFinished &&
                      visiblePayload.state === "submitted"
                        ? "Waiting to download the result."
                        : ["prepared", "queued"].includes(visiblePayload.state)
                          ? "This request has not been sent."
                          : visiblePayload.state === "submitted" &&
                              activeRun(job)
                            ? "Waiting for response."
                            : ["submitted", "uncertain"].includes(
                                  visiblePayload.state,
                                )
                              ? job.mode === "batch"
                                ? "No response recorded. Submission could not be confirmed."
                                : // A Live request is never resent on its own; say how.
                                  "No response recorded, and the provider may or may not have received this request. It is not resent automatically; translate the file again to resend it, which can charge twice if the first one arrived."
                              : ["failed", "rejected"].includes(
                                    visiblePayload.state,
                                  )
                                ? "No response was retained for this attempt."
                                : "The original response was not retained."}
                    </p>
                  )}
                </>
              ) : !visiblePayload ? (
                error || retrying ? null : (
                  <p className="muted" role="status">
                    {busy
                      ? "Reading saved request…"
                      : "No request payload is available. Technical contains the retained run record."}
                  </p>
                )
              ) : (
                <RequestSource payload={visiblePayload} />
              )}
            </TabPanel>
          </div>
        </section>
      </div>
    </div>
  );
}
