import { useSyncExternalStore } from "react";
import type { UpdateState } from "../api/transport";

// One subscription serves the sidebar mark and the Settings panel.
let current: UpdateState | null = null;
const listeners = new Set<() => void>();
let subscribed = false;

function publish(state: UpdateState) {
  current = state;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  if (!subscribed) {
    subscribed = true;
    window.dazedtl.updates.onState(publish);
    window.dazedtl.updates
      .state()
      .then((state) => {
        // A pushed change is newer than this first read.
        if (!current) publish(state);
      })
      .catch(() => undefined);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The app's update state, or null until the main process answers. */
export function useUpdates() {
  return useSyncExternalStore(subscribe, () => current);
}

/** An update needs the user: it is ready, or installing it failed. */
export function updateAttention(state: UpdateState | null) {
  return !!state && (state.status === "ready" || state.outcome?.ok === false);
}
