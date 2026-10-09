export interface DraftState<T> {
  value: T | undefined;
  dirty: boolean;
  committing: boolean;
}
export interface Commit<T> {
  saved: T;
  draft?: T;
}
type Reconcile<T> = (before: T, current: T, result: Commit<T>) => T;
/** Serializes draft writes and explicit saves without owning feature-specific API calls. */
export class DraftSession<T> {
  private state: DraftState<T> = {
    value: undefined,
    dirty: false,
    committing: false,
  };
  private baseline: T | undefined;
  private version = 0;
  private persisted = 0;
  private queue = Promise.resolve();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private listeners = new Set<() => void>();
  private persist!: (value: T) => Promise<unknown>;
  private report!: (error: unknown) => void;
  private fingerprint!: (value: T) => string;
  /** Each write saves the value instead of keeping a recovery draft beside it. */
  private autosave: boolean;
  constructor(
    persist: (value: T) => Promise<unknown>,
    report: (error: unknown) => void,
    {
      fingerprint,
      autosave = false,
    }: { fingerprint?: (value: T) => string; autosave?: boolean } = {},
  ) {
    this.autosave = autosave;
    this.configure(persist, report, fingerprint);
  }
  /** Keeps the owner's latest callbacks; drafts and pending writes are unchanged. */
  configure(
    persist: (value: T) => Promise<unknown>,
    report: (error: unknown) => void,
    fingerprint: (value: T) => string = JSON.stringify,
  ) {
    this.persist = persist;
    this.report = report;
    this.fingerprint = fingerprint;
  }
  fail = (error: unknown) => this.report(error);
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private publish(
    value: T | undefined = this.state.value,
    committing = this.state.committing,
  ) {
    this.state = {
      value,
      committing,
      dirty:
        value !== undefined &&
        this.baseline !== undefined &&
        this.fingerprint(value) !== this.fingerprint(this.baseline),
    };
    for (const listener of this.listeners) listener();
  }
  adopt(saved: T, draft?: T) {
    clearTimeout(this.timer);
    this.baseline = saved;
    this.version++;
    this.persisted = this.version;
    this.publish(draft === undefined ? saved : draft);
  }
  edit(update: T | ((value: T) => T)) {
    if (this.state.value === undefined)
      throw new Error("Wait for the saved values to load.");
    const value =
      typeof update === "function"
        ? (update as (value: T) => T)(this.state.value)
        : update;
    this.version++;
    this.publish(value);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush().catch(this.report), 400);
  }
  private enqueue<R>(action: () => Promise<R>): Promise<R> {
    const task = this.queue.catch(() => {}).then(action);
    this.queue = task.then(
      () => {},
      () => {},
    );
    return task;
  }
  private async persistPending() {
    while (this.state.value !== undefined && this.persisted !== this.version) {
      const ticket = this.version;
      const value = this.state.value;
      await this.persist(value);
      this.persisted = ticket;
      if (this.autosave) {
        this.baseline = value;
        this.publish();
      }
    }
  }
  flush = () => {
    clearTimeout(this.timer);
    return this.enqueue(() => this.persistPending());
  };
  commit = async (
    operation: (value: T) => Promise<Commit<T>>,
    reconcile?: Reconcile<T>,
  ) => {
    clearTimeout(this.timer);
    return this.enqueue(async () => {
      if (this.state.value === undefined)
        throw new Error("Wait for the saved values to load.");
      this.publish(this.state.value, true);
      try {
        await this.persistPending();
        const before = this.state.value!;
        const ticket = this.version;
        const result = await operation(before);
        if (ticket === this.version) this.adopt(result.saved, result.draft);
        else {
          this.baseline = result.saved;
          this.publish(
            reconcile
              ? reconcile(before, this.state.value!, result)
              : this.state.value,
          );
          await this.persistPending();
        }
        return result;
      } finally {
        this.publish(this.state.value, false);
      }
    });
  };
  /**
   * Drops the draft: cancels the delayed write, clears the stored draft after
   * any write already under way, then shows the saved value, so a write due
   * during the clear cannot bring the discarded edit back.
   */
  discard = (saved: T, clear: () => Promise<unknown>) => {
    clearTimeout(this.timer);
    return this.enqueue(async () => {
      await clear();
      this.adopt(saved);
    });
  };
  dispose() {
    clearTimeout(this.timer);
    return this.flush();
  }
}
