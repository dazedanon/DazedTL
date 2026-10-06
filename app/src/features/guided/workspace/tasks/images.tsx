/** Images, hosted in the Guided workspace. */
import type { ReactNode } from "react";
import { imagesApi } from "../../../../api/images";
import { flushDrafts } from "../../../../state/leaveGuards";
import { GuidedImages } from "../../GuidedImages";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

export function imagesView(w: GuidedWorkspace): TaskView {
  const { project, application, action, setImageView, disabled, advance } = w;
  let content: ReactNode, primary: ReactNode;
  content = (
    <GuidedImages
      state={application.snapshot?.images || null}
      error={application.snapshot?.imagesError || ""}
      busy={disabled}
      open={(mode) => {
        void action.run(
          async () => {
            await flushDrafts();
            setImageView(mode);
          },
          "",
          "images:open",
        );
      }}
      copy={() => {
        void action.run(
          async () => {
            await flushDrafts();
            const result = await imagesApi.action(project.id, "edit_task");
            if (!result.text) throw new Error("The image task is unavailable.");
            await window.dazedtl.copyText(result.text);
          },
          "Image task copied. Paste it into your coding assistant.",
          "images:copy",
        );
      }}
      refresh={() => {
        void action.run(
          () => imagesApi.action(project.id, "refresh_results"),
          "Saved image results refreshed.",
          "images:refresh",
        );
      }}
    />
  );
  primary = advance("Continue to text Apply");
  return { content, primary };
}
