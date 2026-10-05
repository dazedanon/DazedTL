import type { Job, RunPayload, RunProcess } from "../../api/contracts.ts";
import { groupedRequests, requestStateLabel } from "./translationView.ts";
import { batchOutcome, type ProviderBatch } from "./batchView.ts";

type Request = NonNullable<RunProcess["requests"]>[number];
/** A provider count never identifies a row; only a bound receipt can do that. */
export function requestOutcome(
  row: Pick<Request, "state" | "providerFinished">,
) {
  if (row.state === "failed" || row.state === "rejected")
    return {
      group: "failed",
      label: row.state === "failed" ? "Failed" : "Validation failed",
    } as const;
  if (row.state === "received")
    return { group: "pending", label: requestStateLabel(row.state) } as const;
  if (["validated", "saved", "unused"].includes(row.state))
    return {
      group: "finished" as const,
      label: requestStateLabel(row.state),
    };
  if (row.state === "submitted" && row.providerFinished)
    return { group: "finished", label: "Finished at provider" } as const;
  return {
    group: "pending" as const,
    label:
      (
        {
          prepared: "Prepared",
          queued: "Queued",
          submitted: "At provider",
          uncertain: "Submission unconfirmed",
        } as Record<string, string>
      )[row.state] || "Status unavailable",
  };
}

export type RequestRow = ReturnType<typeof groupedRequests>[number] & {
  outcome: ReturnType<typeof requestOutcome>;
};
export function requestRows(
  rows: NonNullable<RunProcess["requests"]>,
): RequestRow[] {
  // Group interleaved worker receipts by file, retaining stable request numbers
  // and original indices for payload reads and clarification selection.
  const files = new Map<string, RequestRow[]>();
  for (const row of groupedRequests(rows)) {
    const key = row.file || "";
    if (!files.has(key)) files.set(key, []);
    files.get(key)!.push({ ...row, outcome: requestOutcome(row) });
  }
  return [...files.values()].flat();
}
export type RequestBatch = {
  id: string;
  label: string;
  rows: RequestRow[];
  provider?: ProviderBatch;
  clarifications: ProviderBatch[];
};

/** Counts and file names cannot establish which provider batch owns a request. */
export function requestBatches(
  process: RunProcess,
  mode?: string,
): RequestBatch[] {
  const rows =
    process.requests ||
    Array.from({ length: process.prepared || 0 }, (_, index) => ({
      index,
      state: "unknown",
      sourceItems: 0,
    }));
  if (mode !== "batch")
    return [
      {
        id: "requests",
        label: "Requests",
        rows: requestRows(rows),
        clarifications: [],
      },
    ];
  const assigned = new Set<number>();
  const providers = process.batches || [];
  const originals = new Map(
    providers
      .filter((provider) => !provider.clarification)
      .map((provider) => [provider.id, provider]),
  );
  const owners = new Map(
    providers.map((provider) => [
      provider.id,
      provider.clarification && provider.originalBatchId
        ? originals.get(provider.originalBatchId) || provider
        : provider,
    ]),
  );
  const batches: RequestBatch[] = [...new Set(owners.values())].map(
    (provider, index) => {
      const clarifications = providers.filter(
        (child) => child !== provider && owners.get(child.id) === provider,
      );
      const indices = new Set(
        [provider, ...clarifications].flatMap(
          (batch) => batch.requestIndices || [],
        ),
      );
      const included = rows.filter((row) => indices.has(row.index));
      included.forEach((row) => assigned.add(row.index));
      return {
        id: provider.id,
        label: `Batch ${index + 1}${provider.clarification ? " · Clarification" : ""}`,
        provider,
        clarifications,
        rows: requestRows(included).sort((a, b) => a.index - b.index),
      };
    },
  );
  const remaining = rows.filter((row) => !assigned.has(row.index));
  const queued = remaining.filter((row) =>
    ["queued", "prepared"].includes(row.state),
  );
  const unlinked = remaining.filter(
    (row) => !["queued", "prepared"].includes(row.state),
  );
  if (queued.length)
    batches.push({
      id: "unsent",
      label: "Not submitted",
      rows: requestRows(queued),
      clarifications: [],
    });
  if (unlinked.length)
    batches.push({
      id: "unlinked",
      label: "Requests without a batch receipt",
      rows: requestRows(unlinked),
      clarifications: [],
    });
  return batches;
}

/** A finished original must not hide its pending or failed clarification. */
export function requestBatchOutcome(batch: RequestBatch, job: Job) {
  if (!batch.provider) return undefined;
  const original = batchOutcome(batch.provider, job);
  const retries = batch.clarifications.map((provider) =>
    batchOutcome(provider, job),
  );
  const pending =
    retries.find((outcome) => outcome.active) ||
    retries.find((outcome) => outcome.failed) ||
    retries.find((outcome) => !outcome.successful);
  return !original.active && pending
    ? {
        ...pending,
        label: `Clarification · ${pending.label}`,
        clarification: true,
      }
    : { ...original, clarification: false };
}

/** Keep all attempts in the chosen family, without borrowing another batch's reply. */
export function payloadForBatch(
  payload: RunPayload,
  batchIds?: string | string[],
): RunPayload {
  if (!batchIds || !payload.responseAttempts?.length) return payload;
  const ids = new Set(typeof batchIds === "string" ? [batchIds] : batchIds);
  const attempts = payload.responseAttempts.filter(
    (attempt) => attempt.batchId && ids.has(attempt.batchId),
  );
  return attempts.length
    ? { ...payload, responseAttempts: attempts }
    : {
        ...payload,
        state: "unknown",
        response: null,
        translations: undefined,
        error: null,
        usage: null,
        responseOrigin: null,
        responseAttempts: [],
      };
}
