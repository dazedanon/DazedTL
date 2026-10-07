import { request } from "./transport";
export const pluginsApi = {
  state: (project_id: string) => request("plugins_state", { project_id }),
  action: (
    project_id: string,
    action: string,
    options: Record<string, unknown> = {},
  ) => request("plugins_action", { project_id, action, options }),
  /** Uses another project's saved plugin work here, as it was shown. */
  adopt: (project_id: string, binding: string) =>
    request("plugins_adopt", { project_id, binding }),
  /** Moves another project's saved plugin work aside and starts fresh. */
  startOver: (project_id: string, binding: string) =>
    request("plugins_start_over", { project_id, binding }),
};
