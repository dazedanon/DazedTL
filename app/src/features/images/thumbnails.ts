import { useEffect, useEffectEvent, useState } from "react";
import type { ImageAsset, ImagePixels } from "../../api/contracts";

/** Thumbnail data URLs kept per project, about 2,000 at the largest size. */
const CACHE_BUDGET = 64_000_000;
/** Loading ahead stops short of the cache's budget, so it never evicts. */
const AHEAD_BUDGET = 48_000_000;
type Waiter = (value: ImagePixels | null) => void;
type Load = (
  asset: ImageAsset,
  size: number,
  current: () => boolean,
) => Promise<ImagePixels>;
type Entry = {
  key: string;
  asset: ImageAsset;
  size: number;
  waiters: Set<Waiter>;
  loading: boolean;
  /** Asked for ahead of scrolling, so it returns there when its tile leaves. */
  ahead: boolean;
};
const thumbnailKey = (asset: ImageAsset, size: number) =>
  asset.id + ":" + (asset.candidateHash || asset.sourceHash) + ":" + size;

/**
 * A project-local thumbnail loader with bounded outstanding reads and a cache
 * bounded by size. Images on screen load first; while none wait, the images
 * planned ahead load in order, so scrolling finds them ready.
 */
export class ThumbnailQueue {
  private cache = new Map<string, ImagePixels>();
  private bytes = 0;
  /** Thumbnails queued or loading, by key; one read serves every waiter. */
  private entries = new Map<string, Entry>();
  /** Thumbnails that failed load again only for a tile on screen. */
  private failed = new Set<string>();
  private shown: Entry[] = [];
  private ahead: Entry[] = [];
  private active = 0;
  private closed = false;
  private load: Load;
  constructor(load: Load) {
    this.load = load;
  }
  /** The cached thumbnail, without loading it. */
  peek(asset: ImageAsset, size: number) {
    return this.cache.get(thumbnailKey(asset, size)) ?? null;
  }
  get(asset: ImageAsset, size: number, done: Waiter) {
    const key = thumbnailKey(asset, size);
    const existing = this.cache.get(key);
    if (existing) {
      this.cache.delete(key);
      this.cache.set(key, existing);
      done(existing);
      return () => {};
    }
    let entry = this.entries.get(key);
    if (!entry) {
      entry = this.entry(key, asset, size);
      this.shown.push(entry);
    } else if (!entry.loading && !entry.waiters.size) {
      this.ahead = this.ahead.filter((value) => value !== entry);
      this.shown.push(entry);
    }
    const waiting = entry;
    waiting.waiters.add(done);
    this.pump();
    return () => {
      waiting.waiters.delete(done);
      if (waiting.loading || waiting.waiters.size) return;
      // A tile that leaves before its image loads stops waiting for it.
      this.shown = this.shown.filter((value) => value !== waiting);
      if (waiting.ahead) this.ahead.unshift(waiting);
      else this.entries.delete(key);
    };
  }
  /** Plans `assets` to load in order while nothing on screen waits. */
  prefetch(assets: readonly ImageAsset[], size: number) {
    for (const entry of this.ahead) this.entries.delete(entry.key);
    this.ahead = [];
    for (const asset of assets) {
      const key = thumbnailKey(asset, size);
      if (this.cache.has(key) || this.failed.has(key)) continue;
      const existing = this.entries.get(key);
      if (existing) existing.ahead = true;
      else this.ahead.push(this.entry(key, asset, size, true));
    }
    this.pump();
  }
  dispose() {
    this.closed = true;
    this.shown = [];
    this.ahead = [];
    this.entries.clear();
    this.failed.clear();
    this.cache.clear();
  }
  private entry(key: string, asset: ImageAsset, size: number, ahead = false) {
    const entry: Entry = {
      key,
      asset,
      size,
      waiters: new Set(),
      loading: false,
      ahead,
    };
    this.entries.set(key, entry);
    return entry;
  }
  private store(key: string, value: ImagePixels) {
    const old = this.cache.get(key);
    if (old) this.bytes -= old.url.length;
    this.cache.delete(key);
    this.cache.set(key, value);
    this.bytes += value.url.length;
    while (this.bytes > CACHE_BUDGET) {
      const [oldest, pixels] = this.cache.entries().next().value!;
      this.cache.delete(oldest);
      this.bytes -= pixels.url.length;
    }
  }
  private pump() {
    while (!this.closed && this.active < 4) {
      const entry =
        this.shown.shift() ??
        (this.bytes < AHEAD_BUDGET ? this.ahead.shift() : undefined);
      if (!entry) return;
      entry.loading = true;
      this.active++;
      void this.load(entry.asset, entry.size, () => !this.closed)
        .then(
          (value) => {
            if (this.closed) return;
            this.failed.delete(entry.key);
            this.store(entry.key, value);
            for (const waiter of entry.waiters) waiter(value);
          },
          () => {
            if (this.closed) return;
            this.failed.add(entry.key);
            for (const waiter of entry.waiters) waiter(null);
          },
        )
        .finally(() => {
          if (this.entries.get(entry.key) === entry)
            this.entries.delete(entry.key);
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
  // A thumbnail loaded ahead shows on the tile's first frame.
  return loaded?.key === key ? loaded.pixels : queue.peek(asset, size);
}
