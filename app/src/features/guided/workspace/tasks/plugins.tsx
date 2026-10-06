/** Plugin text, hosted in the Guided workspace. */
import type { ReactNode } from "react";
import { flushDrafts } from "../../../../state/leaveGuards";
import { PluginWorkspace } from "../../../plugins/PluginWorkspace";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function pluginsView(w: GuidedWorkspace): TaskView {
  const { project, application, pluginFooter, disabled, advance, back } = w;
  let content: ReactNode, primary: ReactNode;
  content = (
    <PluginWorkspace
      key={project.id}
      projectId={project.id}
      observed={application.snapshot?.plugins}
      error={application.snapshot?.pluginsError}
      footerTarget={pluginFooter}
      backControl={back()}
      beforeAction={flushDrafts}
      disabled={disabled}
      continueControl={advance(undefined, undefined, "quiet")}
    />
  );
  primary = undefined;
  return {
    content,
    primary,
    heading: {
      description:
        "Paste the task into your coding agent and keep DazedTL open. It continues through safe work automatically and asks only about unresolved choices.",
    },
  };
}
