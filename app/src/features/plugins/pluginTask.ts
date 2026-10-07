import type { PluginState } from "../../api/contracts.ts";
import type { DisplayState } from "../../ui/displayStatus.ts";

/** Plugin files the assistant still has to investigate or translate. */
export const pluginFilesLeft = ({ counts }: PluginState) =>
  counts.files - counts.investigated + counts.textFiles - counts.translated;

/** Files the app cannot read that the user has not chosen to keep unchanged. */
export const pluginFilesBlocked = ({ unreadable }: PluginState) =>
  unreadable.filter((row) => !row.kept);

/**
 * Plugin files is done once every plugin with Japanese text is investigated
 * and its player text translated, with nothing waiting to go into the game
 * and every file the app cannot read kept unchanged.
 */
export const pluginsComplete = (state: PluginState) =>
  state.scanned &&
  !pluginFilesLeft(state) &&
  !state.counts.ready &&
  !pluginFilesBlocked(state).length;

/**
 * Where the plugin task stands, the same in its panel and the task list.
 * The copied task never stops with files left, so files left after a copy
 * changed or appeared since the assistant finished.
 */
export function pluginTaskState(
  state: PluginState,
  { waiting, copied }: { waiting: boolean; copied: boolean },
): Extract<
  DisplayState,
  | "waiting"
  | "ready"
  | "outdated"
  | "not_started"
  | "blocked"
  | "applied"
  | "done"
> {
  const { counts } = state;
  const left = pluginFilesLeft(state);
  if (waiting) return "waiting";
  if (counts.ready) return "ready";
  if (left && copied) return "outdated";
  if (!state.scanned || counts.investigated < counts.files || left)
    return "not_started";
  if (pluginFilesBlocked(state).length) return "blocked";
  return counts.applied ? "applied" : "done";
}
