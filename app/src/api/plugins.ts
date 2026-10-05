import { request } from "./transport";
import type { PluginView } from "./pluginContracts";
import { readQueue } from "./readQueue";
const metadataRead = readQueue(2);
export const pluginsApi = {
  state: (project_id: string) => request("plugins_state", { project_id }),
  list: (
    project_id: string,
    options: {
      query?: string;
      filter?: string;
      selected_only?: boolean;
      offset?: number;
      limit?: number;
    } = {},
    current?: () => boolean,
  ) =>
    metadataRead(
      () => request("plugins_list", { project_id, ...options }),
      current,
    ),
  detail: (project_id: string, file: string, current?: () => boolean) =>
    metadataRead(
      () => request("plugins_detail", { project_id, file }),
      current,
    ),
  update: (project_id: string, revision: string, view: Partial<PluginView>) =>
    request("plugins_update", { project_id, revision, changes: { view } }),
  action: (
    project_id: string,
    action: string,
    options: Record<string, unknown> = {},
  ) => request("plugins_action", { project_id, action, options }),
  continueTask: (project_id: string, request_id: string) =>
    request("plugins_continue", { project_id, request_id }),
};
