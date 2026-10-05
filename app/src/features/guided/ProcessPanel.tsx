import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronRight, LoaderCircle } from "lucide-react";
import type { Job, NameTranslationPage, RunPayload } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { ComboBox } from "../../ui/ComboBox";
import { Message } from "../../ui/Feedback";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { RequestSource } from "./RequestSource";
import { RequestTechnical } from "./RequestTechnical";
import { ExpandableText } from "../../ui/ExpandableText";
import { historyOutcome } from "./historyView";
import { requestAttempt, translatedLines } from "./translationView";
import {
  requestOutcome,
  requestBatches,
  requestBatchOutcome,
  payloadForBatch,
  type RequestBatch,
} from "./requestView";
import { RunTechnical } from "./RunTechnical";
import { RequestFailure } from "./RequestFailure";
import { providerBatchActive } from "./batchView";
import { InspectedFile } from "./InspectedFile";

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
  index?: number;
  validation?: boolean;
};
const inspectorKey = (id: string) => "dazedtl:request-view:" + id;
function savedView(id: string): InspectorView {
  const fallback: InspectorView = { index: 0, tab: "source", batch: null };
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
  return `${job.logicalPhase === "database" ? "Database" : job.logicalPhase === "dialogue" ? "Maps & events" : job.logicalPhase === "advanced" ? "Event / plugin codes" : job.logicalPhase === "variables" ? "Comparisons" : job.logicalPhase === "speakers" ? "Speakers" : "Translation"} · ${job.mode === "batch" ? "Batch" : job.mode === "estimate" ? "Estimate" : "Live"}`;
}
type Props = {
  job: Job;
  readPayload?: (index: number) => Promise<RunPayload>;
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
            : "source",
          batch:
            initialRequest.index == null
              ? "file"
              : requestBatches(process, job.mode).find((batch) =>
                  batch.rows.some((row) =>
                    row.indices.includes(initialRequest.index!),
                  ),
                )?.id || null,
        }
      : savedView(job.id),
  );
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [attemptSelection, setAttemptSelection] = useState<{
    request: number;
    attempt: number;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [fileOpened, setFileOpened] = useState<string>();
  const [unlinkedFile, setUnlinkedFile] = useState(initialRequest?.file);
  const reader = useRef<HTMLDivElement>(null);
  const payloadReader = useRef(readPayload);
  payloadReader.current = readPayload;
  const tabId = useId();
  const attemptTabId = useId();
  const batches = process.batches || [];
  const groups = requestBatches(process, job.mode);
  const selectedBatch =
    job.mode === "batch"
      ? groups.find(
          (batch) =>
            batch.id === view.batch ||
            batch.clarifications.some((child) => child.id === view.batch),
        ) ||
        (view.batch === null
          ? groups[0]
          : ["unsent", "unlinked"].includes(view.batch || "")
            ? groups.find((batch) =>
                batch.rows.some((row) => row.indices.includes(view.index)),
              )
            : undefined)
      : groups[0];
  const selectedProviders = selectedBatch?.provider
    ? [selectedBatch.provider, ...selectedBatch.clarifications]
    : [];
  const requests = selectedBatch?.rows || [];
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
  useEffect(() => {
    let current = true;
    if (index == null || !payloadReader.current) {
      setBusy(false);
      setRetrying(false);
      setError("");
      setPayload(null);
      return;
    }
    setBusy(true);
    setError("");
    void payloadReader
      .current(index)
      .then((value) => {
        if (current) setPayload(value);
      })
      .catch((failure) => {
        if (current)
          setError(
            failure instanceof Error
              ? failure.message
              : "Saved request unavailable.",
          );
      })
      .finally(() => {
        if (current) {
          setBusy(false);
          setRetrying(false);
        }
      });
    return () => {
      current = false;
    };
  }, [index, retry, receiptRevision]);
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
    change({
      batch: batch.id,
      index: batch.rows[0]?.index || 0,
      tab: "source",
    });
  }
  const selectionOutcome =
    selected &&
    (visiblePayload
      ? requestOutcome({
          ...visiblePayload,
          providerFinished: selected.providerFinished,
        })
      : selected.outcome);
  const atProvider =
    (visiblePayload?.state || selected?.state) === "submitted" &&
    !selected?.providerFinished &&
    (job.mode !== "batch" ||
      selectedProviders.some((batch) => providerBatchActive(batch.status)));
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
              {text}
            </td>
            <td>{translated[key]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  const selectedFile = selected ? selected.file : unlinkedFile;
  const contentTabs =
    projectId && selectedFile
      ? [...tabs, { id: "file" as const, label: "File contents" }]
      : tabs;
  const contentTab =
    view.tab === "file" && !(projectId && selectedFile) ? "source" : view.tab;
  useEffect(() => {
    if (contentTab === "file") setFileOpened(selectedFile || undefined);
  }, [contentTab, selectedFile]);
  const legacyIssues = (process.validationIssues || []).filter(
    (issue) =>
      (!selectedFile || issue.file === selectedFile) &&
      !process.requests?.some(
        (row) => row.file === issue.file && row.state === "rejected",
      ),
  );
  const rejected = process.requests?.find((row) => row.state === "rejected");
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
            <span className="muted">{job.files.length} files</span>
          )}
          {job.mode !== "batch" && (
            <span className="badge">{historyOutcome(job).label}</span>
          )}
        </div>
        {(rejected || !!process.validationIssues?.length) && (
          <Button
            variant="quiet"
            onClick={() => {
              setUnlinkedFile(
                rejected?.file || process.validationIssues?.[0].file,
              );
              setAttemptSelection(null);
              change({
                index: rejected?.index ?? -1,
                tab: rejected ? "response" : "json",
                batch: rejected
                  ? groups.find((group) =>
                      group.rows.some((row) =>
                        row.indices.includes(rejected.index),
                      ),
                    )?.id || null
                  : "file",
              });
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
                    : batch.rows.length;
                  const files = [
                    ...new Set(
                      batch.rows.map((row) => row.file).filter(Boolean),
                    ),
                  ];
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
                          {!!files.length && (
                            <small>
                              {files.length}{" "}
                              {files.length === 1 ? "file" : "files"}
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
                  placeholder="No requests"
                  disabled={!requests.length}
                  options={requests.map((row, position) => ({
                    value: String(row.index),
                    label: `Request ${position + 1} of ${requests.length}`,
                    searchText: `Request ${position + 1}\n${row.outcome.label}`,
                    description: row.outcome.label,
                  }))}
                  onChange={(value) => choose(Number(value))}
                />
              </div>
              {selectionOutcome && (
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
                    : "Clarification retry",
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
            <Message message={error} />
            {(error || retrying) && readPayload && (
              <Button
                variant="quiet"
                pending={retrying}
                disabled={busy}
                onClick={() => {
                  setRetrying(true);
                  setRetry((value) => value + 1);
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
                  {visiblePayload.unused.appliedRequests
                    .filter((index) =>
                      requests.some(
                        (row) =>
                          row.index === index &&
                          ["validated", "saved"].includes(row.state),
                      ),
                    )
                    .map((index) => (
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
                      <h3>Event text review</h3>
                      <ExpandableText
                        text={formatted(job.eventTextReview)}
                        label="Event text review"
                      />
                    </section>
                  )}
                </div>
              ) : initialRequest && view.index < 0 ? (
                <p className="muted">
                  {process.noRequestFiles?.includes(initialRequest.file)
                    ? "This file produced no new requests in this pass."
                    : "No saved request is linked to this file in this attempt."}{" "}
                  File contents shows its current text.
                </p>
              ) : selectedBatch?.provider && !requests.length ? (
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
                    <pre>{responseText(visiblePayload.response)}</pre>
                  ) : visiblePayload.error != null ? null : (
                    <p className="muted" role="status">
                      {selected?.providerFinished &&
                      visiblePayload.state === "submitted"
                        ? "Waiting to download the response."
                        : ["prepared", "queued"].includes(visiblePayload.state)
                          ? "This request has not been sent."
                          : visiblePayload.state === "submitted"
                            ? "Waiting for response."
                            : visiblePayload.state === "uncertain"
                              ? "No response recorded. Submission could not be confirmed."
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
