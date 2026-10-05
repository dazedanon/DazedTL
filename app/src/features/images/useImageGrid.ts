import { useEffect, useMemo, useRef, useState } from "react";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import type {
  ImageAsset,
  ImageList,
  ImagePixels,
  ImageView,
} from "../../api/imageContracts";

const PAGE_SIZE = 100;
const MAX_PAGES = 8;
export function useImageGrid(
  projectId: string,
  view: ImageView,
  inventory: string,
  selectionRevision: number,
  start: number,
  end: number,
) {
  const [pages, setPages] = useState<Map<number, ImageAsset[]>>(new Map());
  const [summary, setSummary] = useState({ total: 0, selectedMatched: 0 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
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
  const ticket = useRef(0);
  const cache = useRef(new Map<number, ImageAsset[]>());
  const pending = useRef(new Set<number>());
  const demand = useRef<number[]>([]);
  const active = useRef(0);
  const scopeRef = useRef(scope);
  const pump = useRef<() => void>(() => {});
  useEffect(() => {
    const generation = ++ticket.current;
    scopeRef.current = scope;
    cache.current = new Map();
    pending.current = new Set();
    demand.current = [0];
    setPages(new Map());
    setSummary({ total: 0, selectedMatched: 0 });
    setError("");
    setLoading(true);
    pump.current = () => {
      while (active.current < 2 && demand.current.length) {
        const offset = demand.current.shift()!;
        if (pending.current.has(offset) || cache.current.has(offset)) continue;
        pending.current.add(offset);
        active.current++;
        void imagesApi
          .list(
            projectId,
            {
              query: scope.query,
              folder: scope.folder,
              filter: scope.filter,
              selected_only: scope.selected_only,
              offset,
              limit: PAGE_SIZE,
            },
            () => ticket.current === generation,
          )
          .then((reply: ImageList) => {
            if (ticket.current !== generation) return;
            cache.current.delete(offset);
            cache.current.set(offset, reply.items);
            while (cache.current.size > MAX_PAGES)
              cache.current.delete(cache.current.keys().next().value!);
            setPages(new Map(cache.current));
            setSummary({
              total: reply.total,
              selectedMatched: reply.selectedMatched,
            });
            setError("");
          })
          .catch((error: unknown) => {
            if (ticket.current === generation) setError(messageOf(error));
          })
          .finally(() => {
            active.current--;
            if (ticket.current === generation) pending.current.delete(offset);
            if (ticket.current === generation)
              setLoading(active.current > 0 || demand.current.length > 0);
            pump.current();
          });
      }
    };
    pump.current();
    return () => {
      ticket.current++;
      demand.current = [];
    };
  }, [scope]);
  useEffect(() => {
    const needed: number[] = [];
    for (
      let offset = Math.floor(start / PAGE_SIZE) * PAGE_SIZE;
      offset < Math.max(end, 1);
      offset += PAGE_SIZE
    )
      needed.push(offset);
    demand.current = needed.filter(
      (offset) => !cache.current.has(offset) && !pending.current.has(offset),
    );
    if (demand.current.length) {
      setLoading(true);
      pump.current();
    }
  }, [start, end, scope, pages]);
  const items: { index: number; asset: ImageAsset }[] = [];
  for (let index = start; index < end; index++) {
    const page = pages.get(Math.floor(index / PAGE_SIZE) * PAGE_SIZE);
    const asset = page?.[index % PAGE_SIZE];
    if (asset) items.push({ index, asset });
  }
  return { ...summary, items, loading, error };
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
  const [pixels, setPixels] = useState<ImagePixels | null>(null);
  useEffect(() => {
    setPixels(null);
    return queue.get(asset, size, setPixels);
  }, [queue, asset.id, asset.sourceHash, asset.candidateHash, size]);
  return pixels;
}
