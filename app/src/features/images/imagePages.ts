import type { ImageAsset, ImageList } from "../../api/contracts";

export const PAGE_SIZE = 100;
/** Pages kept per view; a view up to this many pages lists all of its images. */
export const MAX_PAGES = 50;
export type Pages = Map<number, ImageAsset[]>;

/** Drops the oldest pages past MAX_PAGES. */
export const bounded = (pages: Pages) => {
  while (pages.size > MAX_PAGES) pages.delete(pages.keys().next().value!);
  return pages;
};

export type Loaded<Scope extends { filters: unknown }> = {
  scope: Scope;
  pages: Pages;
  /** The pages a refresh replaces, shown until each one reloads. */
  stale: Pages;
  /**
   * The stale pages are the previous view's, which stand in until this
   * view's first page is read, so switching views never draws an empty grid.
   */
  previousView: boolean;
  total: number;
  error: string;
};
/**
 * Where a scope's results start. A refresh of the same filters keeps showing
 * the pages it replaces, so tiles update in place instead of blanking; other
 * filters keep the previous view on screen until their first page arrives.
 */
export const begin = <Scope extends { filters: unknown }>(
  previous: Loaded<Scope>,
  scope: Scope,
): Loaded<Scope> => ({
  scope,
  pages: new Map(),
  stale: bounded(new Map([...previous.stale, ...previous.pages])),
  previousView:
    previous.previousView || previous.scope.filters !== scope.filters,
  total: previous.total,
  error: "",
});
/** A read result for `scope`, which replaces another view's stand-ins. */
export const read = <Scope extends { filters: unknown }>(
  previous: Loaded<Scope>,
  scope: Scope,
): Loaded<Scope> => {
  const base = previous.scope === scope ? previous : begin(previous, scope);
  return base.previousView
    ? { ...base, stale: new Map(), previousView: false }
    : base;
};

/** The view's pages, nearest to `from` first, as many as are kept. */
const nearestPages = (from: number, total: number) =>
  Array.from({ length: Math.ceil(total / PAGE_SIZE) }, (_, page) => ({
    offset: page * PAGE_SIZE,
    distance: Math.abs(page * PAGE_SIZE - from),
  }))
    .sort((a, b) => a.distance - b.distance)
    .slice(0, MAX_PAGES)
    .map(({ offset }) => offset);

/**
 * Reads one view's pages, two at a time: the pages on screen and beside it
 * first, then the rest of the view nearest to `from` first, so scrolling finds
 * its images listed. A page wanted on screen or beside it shows as soon as it
 * is read; the others read ahead show together once the view is read, so the
 * grid renders once for them instead of once per page.
 */
export class PageReader {
  private pages: Pages = new Map();
  private pending = new Set<number>();
  private demand = [0];
  private ahead: number[] = [];
  private wanted = new Set([0]);
  private planned = false;
  private total = 0;
  /** Pages read since they were last shown. */
  private unshown = false;
  private active = 0;
  private closed = false;
  private read: (offset: number) => Promise<ImageList>;
  private show: (pages: Pages, total: number) => void;
  private fail: (error: unknown) => void;
  private from: () => number;
  constructor(options: {
    read: (offset: number, limit: number) => Promise<ImageList>;
    show: (pages: Pages, total: number) => void;
    fail: (error: unknown) => void;
    /** Where the view is scrolled to, when the rest of it is planned. */
    from: () => number;
  }) {
    this.read = (offset) => options.read(offset, PAGE_SIZE);
    this.show = options.show;
    this.fail = options.fail;
    this.from = options.from;
    this.pump();
  }
  /** The pages on screen or beside it not shown yet: read ones show now,
   * the others are read first. */
  want(offsets: readonly number[]) {
    this.wanted = new Set(offsets);
    if (offsets.some((offset) => this.pages.has(offset))) this.flush();
    this.demand = offsets.filter(
      (offset) => !this.pages.has(offset) && !this.pending.has(offset),
    );
    this.pump();
  }
  close() {
    this.closed = true;
  }
  private flush() {
    if (this.closed || !this.unshown) return;
    this.unshown = false;
    this.show(new Map(this.pages), this.total);
  }
  private pump() {
    while (!this.closed && this.active < 2) {
      const offset = this.demand.shift() ?? this.ahead.shift();
      if (offset === undefined) return;
      if (this.pending.has(offset) || this.pages.has(offset)) continue;
      this.pending.add(offset);
      this.active++;
      void this.read(offset)
        .then((reply) => {
          if (this.closed) return;
          if (!this.planned) {
            this.planned = true;
            this.ahead = nearestPages(this.from(), reply.total);
          }
          this.total = reply.total;
          this.pages.delete(offset);
          this.pages.set(offset, reply.items);
          bounded(this.pages);
          this.unshown = true;
          if (this.wanted.has(offset)) this.flush();
        })
        .catch((error: unknown) => {
          if (!this.closed) this.fail(error);
        })
        .finally(() => {
          this.active--;
          this.pending.delete(offset);
          if (!this.pending.size && !this.demand.length && !this.ahead.length)
            this.flush();
          this.pump();
        });
    }
  }
}
