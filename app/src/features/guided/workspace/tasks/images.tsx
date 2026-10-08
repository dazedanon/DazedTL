/** Images: the shared Image Manager, hosted in the Guided workspace. */
import { ImageManager } from "../../../images/ImageManager";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function imagesView(w: GuidedWorkspace): TaskView {
  const {
    project,
    application,
    taskFooter,
    setEditorAssets,
    advance,
    back,
    reviewPending,
  } = w;
  return {
    content: (
      <ImageManager
        key={project.id}
        projectId={project.id}
        observed={application.snapshot?.images}
        foreign={application.snapshot?.imagesForeign}
        footer={{
          target: taskFooter,
          back: back(),
          next: (variant) => advance(undefined, undefined, variant),
        }}
        onOpenEditor={setEditorAssets}
        // Applying goes through the same review as Check's pending changes.
        applyControl={(apply) =>
          reviewPending({
            only: "images",
            label: `Apply to game${apply.ready ? ` (${apply.ready.toLocaleString()})` : ""}`,
            variant: apply.primary ? "primary" : "default",
            blocked:
              apply.blocked ||
              (!apply.ready && "No image in your list is translated yet."),
            choice: { images: apply.ready },
          })
        }
      />
    ),
  };
}
