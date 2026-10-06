import type { GuidedWorkspace } from "../useGuidedWorkspace";
import { applyView, fittingView, qaView, toolsView } from "./apply";
import { namesView, guidanceView, layoutView } from "./context";
import { imagesView } from "./images";
import { pluginsView } from "./plugins";
import { backupView, extractView, formatView, baselineView } from "./prepare";
import { packageView } from "./release";
import { runView } from "./run";
import { phaseView, auditView, sourcesView } from "./translate";
import type { TaskView } from "./view";

const views: Record<string, (w: GuidedWorkspace) => TaskView> = {
  backup: backupView,
  extract: extractView,
  format: formatView,
  baseline: baselineView,
  names: namesView,
  guidance: guidanceView,
  speakers: layoutView,
  database: phaseView,
  dialogue: phaseView,
  "advanced-run": phaseView,
  variables: phaseView,
  audit: auditView,
  sources: sourcesView,
  plugins: pluginsView,
  images: imagesView,
  apply: applyView,
  fitting: fittingView,
  qa: qaView,
  tools: toolsView,
  package: packageView,
};

/** Renders the selected task, or the saved run when no task matches. */
export const renderTask = (w: GuidedWorkspace) =>
  (views[w.taskView] || runView)(w);
