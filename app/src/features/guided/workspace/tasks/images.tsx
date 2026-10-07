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
        footer={{
          target: taskFooter,
          back: back(),
          next: (variant) => advance(undefined, undefined, variant),
        }}
        onOpenEditor={setEditorAssets}
        // Applying goes through the same review as Check's pending changes.
        applyControl={(selection) =>
          reviewPending({
            only: "images",
            label: `Review & apply${selection.ready ? ` (${selection.ready.toLocaleString()})` : ""}`,
            variant: selection.primary ? "primary" : "default",
            blocked:
              selection.blocked ||
              (!selection.ready &&
                (selection.ids.length ? "No selected image is ready." : true)),
            choice: {
              images: { ids: selection.ids, count: selection.ready },
            },
          })
        }
      />
    ),
  };
}
