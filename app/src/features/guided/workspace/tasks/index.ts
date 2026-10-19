import type { GuidedWorkspace } from "../useGuidedWorkspace";
import { qaView } from "./check";
import { estimateView, guidanceView, layoutView, namesView } from "./context";
import { imagesView } from "./images";
import { pluginsView } from "./plugins";
import { packageView } from "./release";
import { runView } from "./run";
import { setupView } from "./setup";
import { auditView, sourcesView } from "./eventSources";
import { phaseView } from "./translate";
import type { TaskView } from "./view";

const views: Record<string, (w: GuidedWorkspace) => TaskView> = {
  setup: setupView,
  names: namesView,
  guidance: guidanceView,
  speakers: layoutView,
  estimate: estimateView,
  database: phaseView,
  dialogue: phaseView,
  "advanced-run": phaseView,
  variables: phaseView,
  audit: auditView,
  sources: sourcesView,
  plugins: pluginsView,
  images: imagesView,
  qa: qaView,
  package: packageView,
};

/** Renders the selected task, or the saved run when no task matches. */
export const renderTask = (w: GuidedWorkspace) =>
  (views[w.taskView] || runView)(w);
