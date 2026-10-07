import { request } from "./transport";
import type { ImageDraft } from "./contracts";
import { readQueue } from "./readQueue";
const metadataRead = readQueue(2);
const pixelRead = readQueue(4);

export const imagesApi = {
  state: (project_id: string) => request("images_state", { project_id }),
  list: (
    project_id: string,
    options: {
      query?: string;
      folder?: string;
      filter?: string;
      offset?: number;
      limit?: number;
      selected_only?: boolean;
      asset_id?: string;
    } = {},
    current?: () => boolean,
  ) =>
    metadataRead(
      () => request("images_list", { project_id, ...options }),
      current,
    ),
  update: (
    project_id: string,
    revision: string,
    changes: Partial<ImageDraft>,
  ) => request("images_update", { project_id, revision, changes }),
  action: (
    project_id: string,
    action: string,
    options: Record<string, unknown> = {},
  ) => request("images_action", { project_id, action, options }),
  /** Uses another project's saved image work here, as it was shown. */
  adopt: (project_id: string, binding: string) =>
    request("images_adopt", { project_id, binding }),
  /** Moves another project's saved image work aside and starts fresh. */
  startOver: (project_id: string, binding: string) =>
    request("images_start_over", { project_id, binding }),
  pixels: (
    project_id: string,
    asset_id: string,
    variant: "source" | "original" | "candidate" = "source",
    size = 0,
    current?: () => boolean,
  ) =>
    pixelRead(
      () => request("images_preview", { project_id, asset_id, variant, size }),
      current,
    ),
};
