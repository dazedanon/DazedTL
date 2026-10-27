import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import { idsBetween } from "./imageSelection";
import { bounded, PAGE_SIZE, PageReader, type Pages } from "./imagePages";
import type {
  ImageAsset,
  ImageList,
  ImageView,
  ImageViewCounts,
} from "../../api/contracts";

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
 * The page of images `start` to `end` of the view's matches, with the rest of
 * the view read after it so scrolling finds its images listed. `revision`
 * reloads them, while saving a different `selection` only recounts the
 * selected matches, so ticking images never reloads the grid and the
 * Recommended view keeps a tile its user just unticked. `applied` of the
 * selected images are in the game, which the list leaves to Applied.
 */
export function useImageGrid(
  projectId: string,
  view: ImageView,
  inventory: string,
  revision: number,
  selection: readonly string[],
  applied: number,
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
  const reader = useRef<PageReader>(null);
  const shownFrom = useEffectEvent(() => start);
  useEffect(() => {
    const { projectId, ...options } = scope.filters;
    let current = true;
    const pages = new PageReader({
      read: (offset, limit) =>
        imagesApi.list(projectId, { ...options, offset, limit }, () => current),
      show: (pages, total) =>
        setLoaded((previous) => ({
          ...(previous.scope === scope ? previous : begin(previous, scope)),
          pages,
          total,
          error: "",
        })),
      fail: (error) =>
        setLoaded((previous) => ({
          ...(previous.scope === scope ? previous : begin(previous, scope)),
          error: messageOf(error),
        })),
      from: () => shownFrom(),
    });
    reader.current = pages;
    return () => {
      current = false;
      pages.close();
      if (reader.current === pages) reader.current = null;
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
  // The pages beside the screen show as soon as they are read too, so the
  // thumbnails near the screen can load ahead of scrolling.
  const beside = [needed[0] - PAGE_SIZE, needed.at(-1)! + PAGE_SIZE].filter(
    (offset) =>
      offset >= 0 &&
      offset < Math.max(grid.total, 1) &&
      !grid.pages.has(offset),
  );
  const wantedKey = [...missing, ...beside].join(",");
  useEffect(() => {
    reader.current?.want(wantedKey.split(",").filter(Boolean).map(Number));
  }, [wantedKey, scope]);
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
  const chosen = selection.length - applied;
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
