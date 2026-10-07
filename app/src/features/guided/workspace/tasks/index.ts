import type { GuidedWorkspace } from "../useGuidedWorkspace";
import { applyView, fittingView, qaView } from "./apply";
import { namesView, guidanceView, layoutView } from "./context";
import { imagesView } from "./images";
import { pluginsView } from "./plugins";
import { packageView } from "./release";
import { runView } from "./run";
import { setupView } from "./setup";
import { phaseView, auditView, sourcesView } from "./translate";
import type { TaskView } from "./view";

const views: Record<string, (w: GuidedWorkspace) => TaskView> = {
  setup: setupView,
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
  package: packageView,
};

/** Renders the selected task, or the saved run when no task matches. */
export const renderTask = (w: GuidedWorkspace) =>
  (views[w.taskView] || runView)(w);
