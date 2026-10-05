import { useLayoutEffect, useRef, useState } from "react";
import { Button } from "../../ui/Button";

export function ImageFolders({
  folders,
  indexed,
  folder,
  ready,
  onChoose,
  onStatus,
}: {
  folders: { path: string; count: number }[];
  indexed: number;
  folder: string;
  ready: number;
  onChoose: (path: string) => void;
  onStatus: (status: string) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const sample = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(500);
  const [rowHeight, setRowHeight] = useState(34);
  const [scroll, setScroll] = useState(0);
  const first = Math.max(0, Math.floor(scroll / rowHeight) - 2);
  const last = Math.min(
    folders.length,
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
      setRowHeight(Math.max(28, Math.ceil(entry.contentRect.height))),
    );
    observer.observe(sample.current);
    return () => observer.disconnect();
  }, [folders.length, first]);
  return (
    <aside className="image-folder-rail" aria-label="Image folders">
      <Button
        className="image-folder-all"
        variant="quiet"
        aria-pressed={!folder}
        onClick={() => onChoose("")}
      >
        <span className="image-folder-name">All images</span>
        <span>{indexed.toLocaleString()}</span>
      </Button>
      <div
        className="image-folder-scroll"
        ref={viewport}
        onScroll={(event) => setScroll(event.currentTarget.scrollTop)}
      >
        <div
          className="image-folder-space"
          style={{ height: folders.length * rowHeight }}
        >
          <div
            className="image-folder-window"
            style={{ transform: `translateY(${first * rowHeight}px)` }}
          >
            {folders.slice(first, last).map((item, index) => (
              <div key={item.path} ref={index === 0 ? sample : undefined}>
                <Button
                  variant="quiet"
                  aria-label={item.path}
                  aria-pressed={folder === item.path}
                  title={item.path}
                  onClick={() => onChoose(item.path)}
                >
                  <span className="image-folder-name">
                    <strong>
                      {item.path === "."
                        ? "Root images"
                        : item.path.split("/").at(-1)}
                    </strong>
                    <small>
                      {item.path.includes("/")
                        ? item.path.slice(0, item.path.lastIndexOf("/"))
                        : "Game root"}
                    </small>
                  </span>
                  <span>{item.count.toLocaleString()}</span>
                </Button>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="image-folder-views">
        <Button variant="quiet" onClick={() => onStatus("ready")}>
          Ready to apply <span>{ready}</span>
        </Button>
      </div>
    </aside>
  );
}
