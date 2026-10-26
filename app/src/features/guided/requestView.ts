import type {
  Job,
  ProcessRequest,
  RunPayload,
  RunProcess,
} from "../../api/contracts.ts";
import { DEFAULT_LANGUAGES } from "../../app/languages.ts";
import { requestStateLabel } from "./translationView.ts";
import { batchOutcome, type ProviderBatch } from "./batchView.ts";

/** A provider count never identifies a row; only a bound receipt can do
 * that. Lines kept unchanged are in the game's *source* language. */
export function requestOutcome(
  row: Pick<ProcessRequest, "state" | "providerFinished" | "keptLines">,
  source = DEFAULT_LANGUAGES.source,
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
      label: row.keptLines
        ? `Passed, ${row.keptLines} ${row.keptLines === 1 ? "line" : "lines"} kept in ${source}`
        : requestStateLabel(row.state),
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

export type RequestRow = ProcessRequest & {
  outcome: ReturnType<typeof requestOutcome>;
};
export const requestRows = (
  rows: ProcessRequest[],
  source = DEFAULT_LANGUAGES.source,
): RequestRow[] =>
  rows.map((row) => ({ ...row, outcome: requestOutcome(row, source) }));
export type RequestBatch = NonNullable<RunProcess["groups"]>[number] & {
  provider?: ProviderBatch;
  clarifications: ProviderBatch[];
};

/**
 * The backend groups requests by the Batch receipts holding them; the current
 * provider status of each comes from the observed receipts.
 */
export function requestBatches(process: RunProcess): RequestBatch[] {
  const receipts = new Map(
    (process.batches || []).map((batch) => [batch.id, batch]),
  );
  return (process.groups || []).map((group) => {
    const [provider, ...clarifications] = group.batches.map((id) =>
      receipts.get(id),
    );
    return {
      ...group,
      provider,
      clarifications: clarifications.filter(
        (batch): batch is ProviderBatch => !!batch,
      ),
    };
  });
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
