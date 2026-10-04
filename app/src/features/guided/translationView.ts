import type { Job, Phase, RunPayload } from "../../api/contracts.ts";

export const activeRun = (run?: Job | null) => !!run && ["ready", "running", "waiting"].includes(run.status);
export function phaseRun(runs: Job[], phase: Phase) {
  const own = runs.filter(run => run.logicalPhase === phase && run.mode !== "estimate" && !run.keptForHistory);
  return own.find(activeRun) || own.find(run => run.process?.batches?.some(batch => ["validating", "in_progress", "finalizing"].includes(batch.status))) || own[0];
}
export function fileStatus(name: string, run?: Job) {
  if (!run || !run.files?.includes(name)) return { label: "Ready", tone: "idle", symbol: "·" };
  const saved = run.availableOutputs?.includes(name) ?? (run.outputsAvailable && !!run.outputs?.[name]);
  if (saved) return run.appliedOutputs?.includes(name)
    ? { label: "Applied", tone: "success", symbol: "✓" }
    : { label: "Saved", tone: "success", symbol: "✓" };
  if (run.outputs?.[name]) return { label: "Output unavailable", tone: "warning", symbol: "!" };
  const states = run.process?.requests?.filter(row => row.file === name).map(row => row.state) || [];
  if (states.includes("uncertain")) return { label: "Check submission", tone: "warning", symbol: "!" };
  if (states.includes("failed")) return { label: "Needs attention", tone: "warning", symbol: "!" };
  if (states.some(state => ["validated", "received"].includes(state))) return { label: "Partial results", tone: "active", symbol: "◐" };
  if (states.includes("submitted")) return { label: "Submitted", tone: "active", symbol: "◷" };
  if (activeRun(run)) return run.progress?.file === name
    ? { label: "Translating", tone: "active", symbol: "◷" } : { label: "Queued", tone: "idle", symbol: "·" };
  if (["failed", "interrupted", "stopped"].includes(run.status)) return { label: "Unfinished", tone: "warning", symbol: "!" };
  return { label: "No saved output", tone: "idle", symbol: "·" };
}

/** Pair only an exact line-key match or the validated Live result of equal length. */
export function translatedLines(payload: RunPayload): Record<string, string> | null {
  const keys = Object.keys(payload.source || {});
  if (!keys.length) return null;
  let value = payload.response;
  const response = value;
  if (Array.isArray(response)) return payload.state === "validated" && response.length === keys.length && response.every(item => typeof item === "string")
    ? Object.fromEntries(keys.map((key, index) => [key, response[index]])) : null;
  // The engine's Batch cache stores the provider's extracted response text.
  if (value && typeof value === "object" && !Array.isArray(value) && "text" in value) value = value.text;
  if (typeof value === "string") {
    try { value = JSON.parse(value.replace(/^\s*```(?:json)?\s*|\s*```\s*$/g, "")); } catch { return null; }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length === keys.length && keys.every(key => typeof record[key] === "string") ? record as Record<string, string> : null;
}

export function requestContext(payload: RunPayload) {
  const format = (value: unknown) => typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return [payload.system != null ? "System instructions\n" + format(payload.system) : "",
    payload.context != null ? "Matched context\n" + format(payload.context) : "",
    ...(Array.isArray(payload.messages) ? payload.messages.map(message => {
      if (!message || typeof message !== "object") return format(message);
      return `${message.role || "Saved"} message\n${format(message.content)}`;
    }) : []),
  ].filter(Boolean).join("\n\n") || "No separate context was recorded. See the exact payload for all retained fields.";
}
