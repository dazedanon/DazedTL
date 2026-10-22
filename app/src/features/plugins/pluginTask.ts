import type { PluginReceipt, PluginState } from "../../api/contracts.ts";
import type { DisplayState } from "../../ui/displayStatus.ts";

/** Plugin files the assistant still has to investigate or translate. */
export const pluginFilesLeft = ({ counts }: PluginState) =>
  counts.files - counts.investigated + counts.textFiles - counts.translated;

/** Files the app cannot read that the user has not chosen to keep unchanged. */
export const pluginFilesBlocked = ({ unreadable }: PluginState) =>
  unreadable.filter((row) => !row.kept);

/**
 * Plugin files is done once every plugin with Japanese text is investigated
 * and its player text translated, every label Text QA found too long for the
 * screen is shortened or kept, nothing waits to go into the game and every
 * file the app cannot read is kept unchanged.
 */
export const pluginsComplete = (state: PluginState) =>
  state.scanned &&
  !pluginFilesLeft(state) &&
  !state.counts.labels &&
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
  if (
    !state.scanned ||
    counts.investigated < counts.files ||
    left ||
    counts.labels
  )
    return "not_started";
  if (pluginFilesBlocked(state).length) return "blocked";
  return counts.applied ? "applied" : "done";
}

/**
 * Recovery's rows, newest application first: one per application, whose
 * newest receipt says whether it is in the game, since undoing it or bringing
 * it back, here or from Checkpoints, records a receipt of its own. A restore
 * that names no application, as a reviewed restore of backups, keeps a row.
 */
export function recoveryRows(receipts: PluginReceipt[]) {
  const byId = new Map(receipts.map((receipt) => [receipt.id, receipt]));
  const origin = (receipt: PluginReceipt): string => {
    if (receipt.mode === "apply") return receipt.applies || receipt.id;
    const taken = receipt.restores && byId.get(receipt.restores);
    return taken ? origin(taken) : receipt.id;
  };
  const rows = new Map<
    string,
    { application: PluginReceipt; latest: PluginReceipt }
  >();
  for (const receipt of receipts) {
    const row = rows.get(origin(receipt));
    if (row) row.latest = receipt;
    else if (receipt.mode === "apply" || !receipt.restores)
      rows.set(origin(receipt), { application: receipt, latest: receipt });
  }
  return [...rows.values()].reverse();
}
