import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import type {
  ImageAsset,
  ImageList,
  ImagePixels,
  ImageView,
} from "../../api/contracts";

const PAGE_SIZE = 100;
const MAX_PAGES = 8;
type Pages = Map<number, ImageAsset[]>;
type Filters = {
  projectId: string;
  query: string;
  folder: string;
  filter: string;
  selected_only: boolean;
};
type Scope = { filters: Filters; inventory: string; revision: number };
type Loaded = {
  scope: Scope;
  pages: Pages;
  /** The pages a refresh replaces, shown until each one reloads. */
  stale: Pages;
  total: number;
  error: string;
};
const bounded = (pages: Pages) => {
  while (pages.size > MAX_PAGES) pages.delete(pages.keys().next().value!);
  return pages;
};
/**
 * Where a scope's results start. A refresh of the same filters keeps showing
 * the pages it replaces, so tiles update in place instead of blanking; other
 * filters start empty.
 */
const begin = (previous: Loaded, scope: Scope): Loaded => ({
  scope,
  pages: new Map(),
  ...(previous.scope.filters === scope.filters
    ? {
        stale: bounded(new Map([...previous.stale, ...previous.pages])),
        total: previous.total,
      }
    : { stale: new Map(), total: 0 }),
  error: "",
});

/**
 * The page of images `start` to `end` of the view's matches. `revision`
 * reloads them, while saving a different `selection` only recounts the
 * selected matches, so choosing images never reloads the grid and the
 * Selected only view keeps a tile its user just deselected.
 */
export function useImageGrid(
  projectId: string,
  view: ImageView,
  inventory: string,
  revision: number,
  selection: readonly string[],
  start: number,
  end: number,
) {
  const filters = useMemo(
    () => ({
      projectId,
      query: view.query,
      folder: view.folder,
      filter: view.status,
      selected_only: view.showSelected,
    }),
    [projectId, view.query, view.folder, view.status, view.showSelected],
  );
  const scope = useMemo(
    () => ({ filters, inventory, revision }),
    [filters, inventory, revision],
  );
  // Results are tagged with their scope, so a new scope starts without
  // resetting state inside an effect.
  const [loaded, setLoaded] = useState<Loaded>(() => ({
    scope,
    pages: new Map(),
    stale: new Map(),
    total: 0,
    error: "",
  }));
  const grid = useMemo(
    () => (loaded.scope === scope ? loaded : begin(loaded, scope)),
    [loaded, scope],
  );
  const cache = useRef(new Map<number, ImageAsset[]>());
  const pending = useRef(new Set<number>());
  const demand = useRef<number[]>([]);
  const active = useRef(0);
  const pump = useRef<() => void>(() => {});
  useEffect(() => {
    let current = true;
    cache.current = new Map();
    pending.current = new Set();
    demand.current = [0];
    pump.current = () => {
      while (active.current < 2 && demand.current.length) {
        const offset = demand.current.shift()!;
        if (pending.current.has(offset) || cache.current.has(offset)) continue;
        pending.current.add(offset);
        active.current++;
        const { projectId, ...options } = scope.filters;
        void imagesApi
          .list(
            projectId,
            { ...options, offset, limit: PAGE_SIZE },
            () => current,
          )
          .then((reply: ImageList) => {
            if (!current) return;
            cache.current.delete(offset);
            cache.current.set(offset, reply.items);
            bounded(cache.current);
            setLoaded((previous) => ({
              ...(previous.scope === scope ? previous : begin(previous, scope)),
              pages: new Map(cache.current),
              total: reply.total,
              error: "",
            }));
          })
          .catch((error: unknown) => {
            if (current)
              setLoaded((previous) => ({
                ...(previous.scope === scope
                  ? previous
                  : begin(previous, scope)),
                error: messageOf(error),
              }));
          })
          .finally(() => {
            active.current--;
            if (current) pending.current.delete(offset);
            pump.current();
          });
      }
    };
    pump.current();
    return () => {
      current = false;
      demand.current = [];
    };
  }, [scope]);
  const needed: number[] = [];
  for (
    let offset = Math.floor(start / PAGE_SIZE) * PAGE_SIZE;
    offset < Math.max(end, 1);
    offset += PAGE_SIZE
  )
    needed.push(offset);
  const missing = needed.filter((offset) => !grid.pages.has(offset));
  const missingKey = missing.join(",");
  useEffect(() => {
    demand.current = missingKey
      .split(",")
      .filter(Boolean)
      .map(Number)
      .filter(
        (offset) => !cache.current.has(offset) && !pending.current.has(offset),
      );
    if (demand.current.length) pump.current();
  }, [missingKey, scope]);
  const items: { index: number; asset: ImageAsset }[] = [];
  for (let index = start; index < end; index++) {
    const offset = Math.floor(index / PAGE_SIZE) * PAGE_SIZE;
    const page = grid.pages.get(offset) ?? grid.stale.get(offset);
    const asset = page?.[index % PAGE_SIZE];
    if (asset) items.push({ index, asset });
  }
  // Selected images the filters hide are counted apart from the pages, for
  // the saved selection. Choosing a shown image leaves that number as it was,
  // so it stays until the next count arrives; a reload or other filters wait
  // for their own.
  const saved = useMemo(() => selection.join("\n"), [selection]);
  const chosen = selection.length;
  const [counted, setCounted] = useState<{ scope: Scope; hidden: number }>();
  useEffect(() => {
    let current = true;
    const { projectId, ...options } = scope.filters;
    void imagesApi
      .list(projectId, { ...options, offset: 0, limit: 1 }, () => current)
      .then(
        (reply: ImageList) => {
          if (current)
            setCounted({ scope, hidden: chosen - reply.selectedMatched });
        },
        // The page reads report the same failure; the count stays unknown.
        () => {},
      );
    return () => {
      current = false;
    };
  }, [scope, saved, chosen]);
  return {
    total: grid.total,
    /** Selected images the filters hide; unknown until counted. */
    hidden:
      counted?.scope === scope
        ? Math.max(0, Math.min(counted.hidden, chosen))
        : null,
    items,
    // Stale pages stand in while a refresh reloads them.
    loading: !grid.error && missing.some((offset) => !grid.stale.has(offset)),
    error: grid.error,
  };
}

/** A project-local queue with bounded outstanding reads and decoded image cache. */
export class ThumbnailQueue {
  private cache = new Map<string, ImagePixels>();
  private queue: {
    key: string;
    load: () => Promise<ImagePixels>;
    done: (value: ImagePixels | null) => void;
  }[] = [];
  private active = 0;
  private closed = false;
  private generation = 0;
  constructor(private projectId: string) {}
  get(
    asset: ImageAsset,
    size: number,
    done: (value: ImagePixels | null) => void,
  ) {
    const variant = asset.candidateHash ? "candidate" : "source";
    const key =
      asset.id + ":" + (asset.candidateHash || asset.sourceHash) + ":" + size;
    const existing = this.cache.get(key);
    if (existing) {
      this.cache.delete(key);
      this.cache.set(key, existing);
      done(existing);
      return () => {};
    }
    let cancelled = false;
    const entry = {
      key,
      load: () =>
        imagesApi.pixels(
          this.projectId,
          asset.id,
          variant,
          size,
          () => !this.closed && !cancelled,
        ),
      done,
    };
    this.queue.push(entry);
    this.pump();
    return () => {
      cancelled = true;
      this.queue = this.queue.filter((value) => value !== entry);
      entry.done = () => {};
    };
  }
  cancelQueued() {
    this.queue = [];
    this.generation++;
  }
  dispose() {
    this.closed = true;
    this.queue = [];
    this.cache.clear();
    this.generation++;
  }
  private pump() {
    while (!this.closed && this.active < 4 && this.queue.length) {
      const entry = this.queue.shift()!;
      const generation = this.generation;
      this.active++;
      void entry
        .load()
        .then((value) => {
          if (this.closed || generation !== this.generation) return;
          this.cache.delete(entry.key);
          this.cache.set(entry.key, value);
          while (this.cache.size > 160)
            this.cache.delete(this.cache.keys().next().value!);
          entry.done(value);
        })
        .catch(() => {
          if (!this.closed && generation === this.generation) entry.done(null);
        })
        .finally(() => {
          this.active--;
          this.pump();
        });
    }
  }
}

export function useThumbnail(
  queue: ThumbnailQueue,
  asset: ImageAsset,
  size: number,
) {
  const key = [asset.id, asset.sourceHash, asset.candidateHash, size].join(":");
  const [loaded, setLoaded] = useState<{
    key: string;
    pixels: ImagePixels | null;
  } | null>(null);
  // Asset objects are recreated by list reads; the key names the image itself.
  const subscribe = useEffectEvent(
    (done: (value: ImagePixels | null) => void) => queue.get(asset, size, done),
  );
  useEffect(
    () => subscribe((pixels) => setLoaded({ key, pixels })),
    [queue, key],
  );
  return loaded?.key === key ? loaded.pixels : null;
}
