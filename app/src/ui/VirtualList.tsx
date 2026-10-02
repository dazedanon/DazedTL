import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

/** Variable-height rows keep enlarged text and wrapped paths fully readable. */
export function VirtualList<T>({ items, itemKey, children, label, focusKey, onFocusReady, empty }: {
  items: T[];
  itemKey: (item: T) => string;
  children: (item: T, index: number) => ReactNode;
  label: string;
  focusKey?: string | null;
  onFocusReady?: (row: HTMLElement) => void;
  empty: ReactNode;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const rows = useRef(new Map<string, HTMLDivElement>());
  const heights = useRef(new Map<string, number>());
  const [revision, measure] = useState(0);
  const [window, setWindow] = useState({ top: 0, height: 400, estimate: 44, width: 0 });
  const keys = useMemo(() => items.map(itemKey), [items, itemKey]);
  const offsets = useMemo(() => {
    const values = [0];
    for (const key of keys) values.push(values[values.length - 1] + (heights.current.get(key) || window.estimate));
    return values;
  }, [keys, revision, window.estimate, window.width]);
  let start = 0;
  while (start < items.length && offsets[start + 1] < window.top) start++;
  let end = start;
  while (end < items.length && offsets[end] < window.top + window.height) end++;
  start = Math.max(0, start - 6);
  end = Math.min(items.length, end + 6);

  useLayoutEffect(() => {
    const element = viewport.current!;
    const observe = () => {
      const style = getComputedStyle(element);
      const estimate = Math.max(32, parseFloat(style.fontSize) * 1.6 + 16);
      setWindow((previous) => {
        if (previous.width !== element.clientWidth || previous.estimate !== estimate) heights.current.clear();
        return { top: element.scrollTop, height: element.clientHeight, estimate, width: element.clientWidth };
      });
    };
    const observer = new ResizeObserver(observe);
    observer.observe(element);
    observe();
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    const observer = new ResizeObserver((entries) => {
      let changed = false;
      for (const entry of entries) {
        const key = (entry.target as HTMLElement).dataset.virtualKey!;
        const height = entry.borderBoxSize[0]?.blockSize || entry.target.getBoundingClientRect().height;
        if (height && heights.current.get(key) !== height) { heights.current.set(key, height); changed = true; }
      }
      if (changed) measure((value) => value + 1);
    });
    for (const row of rows.current.values()) observer.observe(row);
    return () => observer.disconnect();
  }, [start, end, keys]);
  useLayoutEffect(() => {
    if (!focusKey) return;
    const index = keys.indexOf(focusKey);
    if (index < 0) return;
    const element = viewport.current!;
    if (offsets[index] < element.scrollTop || offsets[index + 1] - offsets[index] > element.clientHeight) element.scrollTop = offsets[index];
    else if (offsets[index + 1] > element.scrollTop + element.clientHeight)
      element.scrollTop = offsets[index + 1] - element.clientHeight;
    setWindow((previous) => previous.top === element.scrollTop ? previous : { ...previous, top: element.scrollTop });
    const row = rows.current.get(focusKey);
    // Let wrapped rows preceding the target settle before releasing the focus
    // request; otherwise their measurements can move the new focus offscreen.
    if (row && keys.slice(start, index + 1).every((key) => heights.current.has(key))) onFocusReady?.(row);
  }, [focusKey, keys, offsets, start, end, onFocusReady]);
  useLayoutEffect(() => {
    const element = viewport.current!;
    const maximum = Math.max(0, offsets[offsets.length - 1] - element.clientHeight);
    if (element.scrollTop > maximum) {
      element.scrollTop = maximum;
      setWindow((previous) => ({ ...previous, top: element.scrollTop }));
    }
  }, [offsets]);
  return <div className="virtual-list" ref={viewport} role="list" aria-label={label}
    onScroll={(event) => { const top = event.currentTarget.scrollTop; setWindow((previous) => ({ ...previous, top })); }}>
    {!items.length ? empty : <>
      <div aria-hidden="true" style={{ height: offsets[start] }} />
      {items.slice(start, end).map((item, index) => <div key={keys[start + index]} role="listitem"
        aria-posinset={start + index + 1} aria-setsize={items.length} data-virtual-key={keys[start + index]}
        ref={(element) => { if (element) rows.current.set(keys[start + index], element); else rows.current.delete(keys[start + index]); }}>
        {children(item, start + index)}
      </div>)}
      <div aria-hidden="true" style={{ height: offsets[offsets.length - 1] - offsets[end] }} />
    </>}
  </div>;
}
