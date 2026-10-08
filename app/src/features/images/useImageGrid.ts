import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import { idsBetween } from "./imageSelection";
import type {
  ImageAsset,
  ImageList,
  ImageView,
  ImageViewCounts,
} from "../../api/contracts";

const PAGE_SIZE = 100;
/** Pages kept per view; a view up to this many pages lists all of its images. */
const MAX_PAGES = 50;
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
 * The page of images `start` to `end` of the view's matches, with the rest of
 * the view read after it so scrolling finds its images listed. `revision`
 * reloads them, while saving a different `selection` only recounts the
 * selected matches, so ticking images never reloads the grid and the
 * To translate view keeps a tile its user just unticked.
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
  const ahead = useRef<number[]>([]);
  const active = useRef(0);
  const pump = useRef<() => void>(() => {});
  const shownFrom = useEffectEvent(() => start);
  useEffect(() => {
    let current = true;
    let planned = false;
    cache.current = new Map();
    pending.current = new Set();
    demand.current = [0];
    ahead.current = [];
    pump.current = () => {
      while (active.current < 2) {
        // Pages on screen come first; the rest of the view follows,
        // nearest first, once the first reply gives its size.
        const offset = demand.current.shift() ?? ahead.current.shift();
        if (offset === undefined) break;
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
            if (!planned) {
              planned = true;
              ahead.current = nearestPages(shownFrom(), reply.total);
            }
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
      ahead.current = [];
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
  const shown = (index: number) => {
    const offset = Math.floor(index / PAGE_SIZE) * PAGE_SIZE;
    return (grid.pages.get(offset) ?? grid.stale.get(offset))?.[
      index % PAGE_SIZE
    ];
  };
  const items: { index: number; asset: ImageAsset }[] = [];
  for (let index = start; index < end; index++) {
    const asset = shown(index);
    if (asset) items.push({ index, asset });
  }
  const listed = useMemo(
    () =>
      [...grid.pages].flatMap(([offset, assets]) =>
        assets.map((asset, at) => ({ index: offset + at, asset })),
      ),
    [grid.pages],
  );
  // Selected images the filters hide are counted apart from the pages, for
  // the saved selection. Choosing a shown image leaves that number as it was,
  // so it stays until the next count arrives; a reload or other filters wait
  // for their own.
  const saved = useMemo(() => selection.join("\n"), [selection]);
  const chosen = selection.length;
  const [counted, setCounted] = useState<{
    scope: Scope;
    hidden: number;
    views?: ImageViewCounts;
  }>();
  useEffect(() => {
    let current = true;
    const { projectId, ...options } = scope.filters;
    void imagesApi
      .list(projectId, { ...options, offset: 0, limit: 1 }, () => current)
      .then(
        (reply: ImageList) => {
          if (current)
            setCounted({
              scope,
              hidden: chosen - reply.selectedMatched,
              views: reply.views,
            });
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
    /**
     * How many images each view lists in this folder and search; the last
     * count stands in while a new one is read.
     */
    views: counted?.views,
    items,
    /** Every image of the view read so far, on screen or not. */
    listed,
    // Stale pages stand in while a refresh reloads them.
    loading: !grid.error && missing.some((offset) => !grid.stale.has(offset)),
    error: grid.error,
    /** The ids of matches `first` to `last`, as shown or read for the view. */
    ids: (first: number, last: number) =>
      idsBetween(
        first,
        Math.min(last, grid.total - 1),
        (index) => shown(index)?.id,
        async (offset, limit) => {
          const { projectId, ...options } = scope.filters;
          const reply = await imagesApi.list(projectId, {
            ...options,
            offset,
            limit,
          });
          return reply.items.map((item) => item.id);
        },
      ),
  };
}
