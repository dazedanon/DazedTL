import type { Phase, Project } from "../../../api/contracts";
import { displayText } from "../../../ui/displayText";

export const speakers = [
  "NAMES",
  "FIRSTLINESPEAKERS",
  "INLINE401SPEAKERS",
  "FACENAME101",
  "AUTONAMEPOPUP101",
  "SPEAKERS408",
];
export const advanced = [
  "CODE122",
  "CODE122_VAR_RANGES",
  "CODE357",
  "ENABLED_PLUGINS_357",
  "CODE355655",
  "ENABLED_PATTERNS_355655",
  "CODE657",
  "CODE356",
  "CODE320",
  "CODE324",
  "CODE325",
  "CODE108",
];
export const advancedCodes = advanced.filter(
  (key) => key.startsWith("CODE") && key !== "CODE122_VAR_RANGES",
);
export const phaseLabels: Record<Phase, string> = {
  database: "Database files",
  dialogue: "Maps & events",
  variables: "Update comparisons",
  advanced: "Event / plugin codes",
  speakers: "Optional name translation",
};
export const actionKey = (
  name: string,
  options: Record<string, unknown> = {},
) =>
  name === "start"
    ? `start:${displayText(options.mode)}:${displayText(options.phase) || "speakers"}`
    : name === "runtime_restore"
      ? `runtime_restore:${displayText(options.publication)}`
      : name === "export_selected" && options.run_id
        ? `export_selected:${displayText(options.run_id)}`
        : name;
export const jobTime = (job: { updated?: string; created?: string }) =>
  Date.parse(job.updated || job.created || "") || 0;
export const fileCount = (count: number) =>
  `${count} ${count === 1 ? "file" : "files"}`;
export const pathKey = (name: string) => name;
export const publicationLabels: Record<string, string> = {
  rewrap_apply: "Text fitting",
  qa_apply: "QA corrections",
  runtime_restore: "Text restore",
  export_selected: "Translations",
};
/** A saved text batch in words: what it was and what became of it. */
export const publicationTitle = (row: { kind: string; state: string }) =>
  row.kind === "runtime_restore" && row.state === "complete"
    ? "Text restored"
    : `${publicationLabels[row.kind] || "Text"} · ${
        row.state === "restored"
          ? "undone by a restore"
          : row.state === "complete"
            ? "applied"
            : row.state.replaceAll("_", " ")
      }`;
export type Panel =
  | "files"
  | "speakers"
  | "speaker-names"
  | "widths"
  | "translation-context"
  | "tools"
  | "preparation"
  | "release-assets"
  | null;
export const panelTitles: Record<Exclude<Panel, null>, string> = {
  files: "Choose files for this pass",
  speakers: "Speaker detection",
  "speaker-names": "Speaker names",
  widths: "Character limits",
  "translation-context": "Translation options",
  tools: "Configure game tools",
  preparation: "Preparation tools",
  "release-assets": "Additional runtime assets",
};
/** A review the Project page asks the Translation workspace to open. */
export type GuidedIntent =
  | { kind: "checkpoint" }
  | { kind: "reapply"; runId: string }
  | { kind: "resume"; runId: string };
/** Project tools live on the Project page; tasks link to their tab. */
export type ProjectLink = (
  tab: "history" | "versions" | "backups",
  historyQuery?: string,
) => void;
export type GuidedProps = {
  project: Project;
  opening?: boolean;
  settings: () => void;
  openProject: ProjectLink;
  intent?: GuidedIntent | null;
  intentHandled?: () => void;
};
