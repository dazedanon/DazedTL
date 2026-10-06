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
type Grid = {
  pages: Map<number, ImageAsset[]>;
  total: number;
  selectedMatched: number;
  error: string;
};
type Loaded = Grid & { scope: object };
const emptyGrid: Grid = {
  pages: new Map(),
  total: 0,
  selectedMatched: 0,
  error: "",
};
export function useImageGrid(
  projectId: string,
  view: ImageView,
  inventory: string,
  selectionRevision: number,
  start: number,
  end: number,
) {
  const scope = useMemo(
    () => ({
      projectId,
      query: view.query,
      folder: view.folder,
      filter: view.status,
      selected_only: view.showSelected,
      inventory,
      selectionRevision,
    }),
    [
      projectId,
      view.query,
      view.folder,
      view.status,
      view.showSelected,
      inventory,
      selectionRevision,
    ],
  );
  // Results are tagged with their scope, so a new scope starts empty without
  // resetting state inside an effect.
  const [loaded, setLoaded] = useState<Loaded>({ scope, ...emptyGrid });
  const grid = loaded.scope === scope ? loaded : emptyGrid;
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
        void imagesApi
          .list(
            scope.projectId,
            {
              query: scope.query,
              folder: scope.folder,
              filter: scope.filter,
              selected_only: scope.selected_only,
              offset,
              limit: PAGE_SIZE,
            },
            () => current,
          )
          .then((reply: ImageList) => {
            if (!current) return;
            cache.current.delete(offset);
            cache.current.set(offset, reply.items);
            while (cache.current.size > MAX_PAGES)
              cache.current.delete(cache.current.keys().next().value!);
            setLoaded({
              scope,
              pages: new Map(cache.current),
              total: reply.total,
              selectedMatched: reply.selectedMatched,
              error: "",
            });
          })
          .catch((error: unknown) => {
            if (current)
              setLoaded((previous) => ({
                ...(previous.scope === scope ? previous : emptyGrid),
                scope,
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
    const page = grid.pages.get(Math.floor(index / PAGE_SIZE) * PAGE_SIZE);
    const asset = page?.[index % PAGE_SIZE];
    if (asset) items.push({ index, asset });
  }
  return {
    total: grid.total,
    selectedMatched: grid.selectedMatched,
    items,
    loading: !grid.error && missing.length > 0,
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
