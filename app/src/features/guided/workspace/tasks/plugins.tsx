/** Plugin files, hosted in the Guided workspace. */
import type { ReactNode } from "react";
import { flushDrafts } from "../../../../state/leaveGuards";
import { PluginWorkspace } from "../../../plugins/PluginWorkspace";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function pluginsView(w: GuidedWorkspace): TaskView {
  const { project, application, taskFooter, disabled, advance, back } = w;
  let content: ReactNode;
  content = (
    <PluginWorkspace
      key={project.id}
      projectId={project.id}
      observed={application.snapshot?.plugins}
      error={application.snapshot?.pluginsError}
      foreign={application.snapshot?.pluginsForeign}
      footerTarget={taskFooter}
      backControl={back()}
      beforeAction={flushDrafts}
      disabled={disabled}
      next={(variant) => advance(undefined, undefined, variant)}
    />
  );
  return {
    content,
    heading: {
      description: "Translate the text plugins show to players.",
    },
  };
}
