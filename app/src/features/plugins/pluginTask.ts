import type { PluginState } from "../../api/contracts.ts";

/** Plugin files the assistant still has to investigate or translate. */
export const pluginFilesLeft = ({ counts }: PluginState) =>
  counts.files - counts.investigated + counts.textFiles - counts.translated;

/**
 * Plugin files is done once every plugin with Japanese text is investigated
 * and its player text translated, with nothing waiting to go into the game.
 */
export const pluginsComplete = (state: PluginState) =>
  state.scanned && !pluginFilesLeft(state) && !state.counts.ready;
