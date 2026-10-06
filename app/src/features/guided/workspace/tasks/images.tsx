/** Images: the shared Image Manager, hosted in the Guided workspace. */
import { ImageManager } from "../../../images/ImageManager";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function imagesView(w: GuidedWorkspace): TaskView {
  const { project, application, taskFooter, setEditorAssets, advance, back } =
    w;
  return {
    content: (
      <ImageManager
        key={project.id}
        projectId={project.id}
        observed={application.snapshot?.images}
        embedded={{
          footerTarget: taskFooter,
          back: back(),
          next: (variant) => advance(undefined, undefined, variant),
        }}
        onOpenEditor={setEditorAssets}
      />
    ),
    primary: undefined,
  };
}
