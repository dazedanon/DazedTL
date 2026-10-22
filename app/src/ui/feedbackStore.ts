import { type DisplayState, displayMarks } from "./displayStatus.ts";

/**
 * Who reports each action's result within a scope, so every status shows
 * once: the action keys whose result a mounted control shows beside itself,
 * and the states of mounted status headings that show an action's outcome.
 */
export class FeedbackStore {
  private owners = new Map<string, number>();
  private outcomes = new Map<string, Map<symbol, DisplayState>>();
  private listeners = new Set<() => void>();

  /** Marks key's result as shown by a control until the returned call. */
  register(key: string) {
    this.owners.set(key, (this.owners.get(key) || 0) + 1);
    this.notify();
    return () => {
      const count = (this.owners.get(key) || 1) - 1;
      if (count) this.owners.set(key, count);
      else this.owners.delete(key);
      this.notify();
    };
  }

  has = (key: string) => this.owners.has(key);

  /** Records a heading that shows key's outcome as state, until the returned call. */
  report(key: string, state: DisplayState) {
    const token = Symbol(key);
    const headings = this.outcomes.get(key) || new Map<symbol, DisplayState>();
    headings.set(token, state);
    this.outcomes.set(key, headings);
    this.notify();
    return () => {
      headings.delete(token);
      if (!headings.size) this.outcomes.delete(key);
      this.notify();
    };
  }

  /**
   * Whether a heading already says key's work finished, with the done mark,
   * so a success beside key's control would say the same thing again.
   */
  saysDone = (key: string) =>
    [...(this.outcomes.get(key)?.values() || [])].some(
      (state) => displayMarks[state] === "done",
    );

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private notify() {
    for (const listener of this.listeners) listener();
  }
}
