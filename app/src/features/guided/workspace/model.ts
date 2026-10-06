import type { ReactNode } from "react";
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
  export_selected: "Text Apply",
};
export type Panel =
  | "tasks"
  | "files"
  | "backups"
  | "versions"
  | "speakers"
  | "speaker-names"
  | "name-translation"
  | "widths"
  | "translation-context"
  | "tools"
  | "project-tools"
  | "preparation"
  | "release-assets"
  | null;
export const panelTitles: Record<Exclude<Panel, null>, string> = {
  tasks: "Translation tasks",
  files: "Choose files for this pass",
  backups: "Backups & recovery",
  versions: "Game updates",
  speakers: "Speaker detection",
  "speaker-names": "Speaker names",
  "name-translation": "API name translation",
  widths: "Character limits",
  "translation-context": "Translation options",
  tools: "Configure game tools",
  "project-tools": "Project tools",
  preparation: "Preparation tools",
  "release-assets": "Additional runtime assets",
};
export type GuidedProps = {
  project: Project;
  opening?: boolean;
  settings: () => void;
  backups?: (target: HTMLElement | null) => ReactNode;
  versions?: (actions: {
    backups: () => void;
    prepare: () => void;
    checkpoint: () => void;
    target: HTMLElement | null;
  }) => ReactNode;
};
