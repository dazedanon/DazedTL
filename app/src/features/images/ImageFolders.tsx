import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Button } from "../../ui/Button";
import { folderTree } from "./imageSelection";

export function ImageFolders({
  folders,
  indexed,
  folder,
  onChoose,
}: {
  folders: { path: string; count: number }[];
  indexed: number;
  folder: string;
  onChoose: (path: string) => void;
}) {
  const rows = useMemo(() => folderTree(folders), [folders]);
  const viewport = useRef<HTMLDivElement>(null);
  const sample = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(500);
  const [rowHeight, setRowHeight] = useState(30);
  const [scroll, setScroll] = useState(0);
  const first = Math.max(0, Math.floor(scroll / rowHeight) - 2);
  const last = Math.min(
    rows.length,
    Math.ceil((scroll + height) / rowHeight) + 2,
  );
  useLayoutEffect(() => {
    if (!viewport.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setHeight(entry.contentRect.height),
    );
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    if (!sample.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setRowHeight(Math.max(24, Math.ceil(entry.contentRect.height))),
    );
    observer.observe(sample.current);
    return () => observer.disconnect();
  }, [rows.length, first]);
  // The list renders only nearby rows, so a saved or chosen folder further
  // down would be neither visible nor marked; it comes into view when the
  // choice changes, never while the user scrolls the list.
  const revealed = useRef<string | null>(null);
  useLayoutEffect(() => {
    const element = viewport.current;
    const index = rows.findIndex((item) => item.path === folder);
    if (!element || revealed.current === folder) return;
    if (index < 0) {
      if (!folder) revealed.current = folder;
      return;
    }
    revealed.current = folder;
    const top = index * rowHeight;
    if (
      top < element.scrollTop ||
      top + rowHeight > element.scrollTop + element.clientHeight
    )
      element.scrollTop = Math.max(0, top - element.clientHeight / 2);
  }, [folder, rows, rowHeight]);
  return (
    <aside className="image-folder-rail" aria-label="Image folders">
      <Button
        className="image-folder-all"
        variant="quiet"
        aria-pressed={!folder}
        onClick={() => onChoose("")}
      >
        <span className="image-folder-name">All folders</span>
        <span>{indexed.toLocaleString()}</span>
      </Button>
      <div
        className="image-folder-scroll"
        ref={viewport}
        onScroll={(event) => setScroll(event.currentTarget.scrollTop)}
      >
        <div
          className="image-folder-space"
          style={{ height: rows.length * rowHeight }}
        >
          <div
            className="image-folder-window"
            style={{ transform: `translateY(${first * rowHeight}px)` }}
          >
            {rows.slice(first, last).map((item, index) => (
              <div key={item.path} ref={index === 0 ? sample : undefined}>
                <Button
                  variant="quiet"
                  aria-label={item.path === "." ? item.name : item.path}
                  aria-pressed={folder === item.path}
                  title={item.path === "." ? item.name : item.path}
                  style={{ "--folder-depth": item.depth } as CSSProperties}
                  onClick={() => onChoose(item.path)}
                >
                  <span className="image-folder-name">{item.name}</span>
                  <span>{item.count.toLocaleString()}</span>
                </Button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}
