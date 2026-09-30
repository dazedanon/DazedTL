import { api } from "../api/client";
import { ApiError, messageOf } from "../api/errors";
import { onMutation } from "../api/transport";
import type { WorkspaceSnapshot } from "../api/contracts";

interface State {
  snapshot: WorkspaceSnapshot | null;
  error: string;
  stopped: boolean;
}
/** One observer per window. Reads never overlap or replace a newer mutation. */
export class ApplicationStore {
  private value: State = { snapshot: null, error: "", stopped: false };
  private listeners = new Set<() => void>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private inFlight: Promise<void> | null = null;
  private requested = false;
  private epoch = 0;
  private readingEpoch = -1;
  private mutations = 0;
  private idleWaiters = new Set<() => void>();
  private started = false;
  private unwatch: (() => void) | undefined;
  private unstopped: (() => void) | undefined;
  getSnapshot = () => this.value;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private publish(value: State) {
    this.value = value;
    for (const listener of this.listeners) listener();
  }
  clearError = () => this.publish({ ...this.value, error: "" });
  start() {
    if (this.started) return;
    this.started = true;
    this.unwatch = onMutation((phase) => {
      clearTimeout(this.timer);
      if (phase === "begin") {
        this.epoch++;
        this.mutations++;
      } else {
        this.mutations = Math.max(0, this.mutations - 1);
        if (!this.mutations) {
          for (const resume of this.idleWaiters) resume();
          this.idleWaiters.clear();
          void this.refresh();
        }
      }
    });
    this.unstopped = window.dazedtl.onStopped((message) => {
      clearTimeout(this.timer);
      this.publish({ ...this.value, error: message, stopped: true });
    });
    void this.refresh();
  }
  stop() {
    this.started = false;
    this.epoch++;
    clearTimeout(this.timer);
    this.unwatch?.();
    this.unstopped?.();
    for (const resume of this.idleWaiters) resume();
    this.idleWaiters.clear();
  }
  refresh = (): Promise<void> => {
    if (!this.started || this.value.stopped) return Promise.resolve();
    clearTimeout(this.timer);
    if (this.inFlight) {
      if (this.readingEpoch !== this.epoch) this.requested = true;
      return this.inFlight;
    }
    this.inFlight = this.read().finally(() => {
      this.inFlight = null;
      if (
        this.started &&
        !this.value.stopped &&
        !this.value.error &&
        this.value.snapshot?.application.running
      )
        this.timer = setTimeout(() => void this.refresh(), 500);
    });
    return this.inFlight;
  };
  private async read() {
    do {
      this.requested = false;
      if (this.mutations)
        await new Promise<void>((resolve) => this.idleWaiters.add(resolve));
      if (!this.started || this.value.stopped) return;
      const ticket = this.epoch;
      this.readingEpoch = ticket;
      try {
        const snapshot = await api.snapshot();
        if (ticket === this.epoch && !this.mutations && this.started)
          this.publish({ snapshot, error: "", stopped: false });
      } catch (error) {
        if (ticket === this.epoch && this.started)
          this.publish({
            ...this.value,
            error: messageOf(error),
            stopped:
              error instanceof ApiError &&
              ["unavailable", "protocol"].includes(error.code),
          });
      }
      if (ticket !== this.epoch) this.requested = true;
    } while (this.started && !this.value.stopped && this.requested);
  }
}
