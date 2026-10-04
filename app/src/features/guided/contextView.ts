import type { GuidedState } from "../../api/contracts.ts";
import { guidanceAvailability, guidanceTitle } from "./guidanceReview.ts";

export type InvestigationPart = "formats" | "names" | "guidance";
export interface InvestigationResult {
  id: InvestigationPart;
  title: string;
  saved: boolean;
  status: "saved" | "waiting" | "idle" | "working" | "failed" | "unavailable";
  detail: string;
}

/** Saved artifacts and the latest local attempt are separate observations. */
export function investigationResults(state: Pick<GuidedState, "speakerSetup" | "speakerScan" | "contextSetup">): InvestigationResult[] {
  const findings = state.speakerSetup, scan = state.speakerScan, context = state.contextSetup;
  const formatsSaved = !!findings.reportId;
  const scanSaved = scan.available ?? scan.current;
  const scanning = !!scan.job && ["ready", "running"].includes(scan.job.status);
  const failed = !!scan.job && ["failed", "interrupted", "stopped", "canceled"].includes(scan.job.status);
  const guidance = guidanceAvailability(context.documents);
  return [
    { id: "formats", title: "Speaker formats", saved: formatsSaved,
      status: formatsSaved ? "saved" : findings.status === "invalid" ? "unavailable" : findings.status === "waiting" ? "waiting" : "idle",
      detail: formatsSaved ? `${findings.rules.length} optional formats investigated${findings.status === "applied" ? " · settings applied" : ""}.`
        : findings.status === "invalid" ? findings.message : "The assistant identifies name tags, faces and speaker patterns." },
    { id: "names", title: "Speaker names", saved: scanSaved,
      status: scanning ? "working" : scanSaved ? "saved" : failed ? "failed" : scan.issue ? "unavailable" : "idle",
      detail: scanning ? scan.job!.message || "Scanning local event files…" : scanSaved ? `${scan.names.length} nameplates · ${scan.files} event files${failed ? " · latest scan did not finish" : ""}.`
        : failed ? scan.job!.message || "The local scan did not finish. Open the scan to retry." : scan.issue || "A local scan collects source names without using the API." },
    { id: "guidance", title: "Glossary & context", saved: guidance.complete,
      status: guidance.complete ? "saved" : context.requestId ? "waiting" : "idle",
      detail: guidance.complete ? "Glossary, style and game context are in the game folder."
        : `${3 - guidance.missing.length} of 3 files saved${guidance.missing.length ? " · remaining: " + guidance.missing.map(guidanceTitle).join(", ") : ""}.` },
  ];
}
