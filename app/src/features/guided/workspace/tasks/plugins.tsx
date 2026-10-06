/** Plugin text, hosted in the Guided workspace. */
import type { ReactNode } from "react";
import { flushDrafts } from "../../../../state/leaveGuards";
import { PluginWorkspace } from "../../../plugins/PluginWorkspace";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function pluginsView(w: GuidedWorkspace): TaskView {
  const { project, application, pluginFooter, disabled, advance } = w;
  let content: ReactNode, primary: ReactNode;
  content = (
    <PluginWorkspace
      key={project.id}
      projectId={project.id}
      observed={application.snapshot?.plugins}
      error={application.snapshot?.pluginsError}
      footerTarget={pluginFooter}
      beforeAction={flushDrafts}
      disabled={disabled}
      continueControl={advance("Continue to Images", undefined, "quiet")}
    />
  );
  primary = undefined;
  return { content, primary };
}
