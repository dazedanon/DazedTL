import { useLayoutEffect, useRef, useState } from "react";
import { Image as ImageIcon } from "lucide-react";
import type { ImageAsset } from "../../api/contracts";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import { useRead } from "../../state/useRead";
import { Button } from "../../ui/Button";
import { FileName } from "../../ui/FileName";
import { StatusMark } from "../../ui/StatusMark";
import { imageDisplay } from "../../ui/displayStatus";
import { imageStatus } from "./imageSelection";
import { type ThumbnailQueue, useThumbnail } from "./useImageGrid";

/** The largest size the backend scales to; larger images are read at it. */
const LARGEST_SCALED = 2048;

/** The image last clicked or moved to in the grid, as large as its panel. */
export function ImageViewer({
  projectId,
  asset,
  queue,
  tileSize,
  onCompare,
}: {
  projectId: string;
  asset: ImageAsset | null;
  queue: ThumbnailQueue;
  tileSize: number;
  onCompare: (asset: ImageAsset) => void;
}) {
  return (
    <figure className="image-viewer" aria-label="Image viewer">
      {asset ? (
        <Viewer
          key={asset.id}
          projectId={projectId}
          asset={asset}
          queue={queue}
          tileSize={tileSize}
          onCompare={() => onCompare(asset)}
        />
      ) : (
        <div className="image-viewer-canvas image-viewer-empty">
          <ImageIcon size={24} aria-hidden="true" />
          <span>Click an image to preview it.</span>
        </div>
      )}
    </figure>
  );
}

function Viewer({
  projectId,
  asset,
  queue,
  tileSize,
  onCompare,
}: {
  projectId: string;
  asset: ImageAsset;
  queue: ThumbnailQueue;
  tileSize: number;
  onCompare: () => void;
}) {
  // The tile's thumbnail, usually already loaded, stands in until the full
  // image arrives.
  const thumbnail = useThumbnail(queue, asset, tileSize);
  const variant = asset.candidateHash ? "candidate" : "source";
  const largest = Math.max(asset.width || 0, asset.height || 0);
  const full = useRead(
    [projectId, asset.id, asset.sourceHash, asset.candidateHash].join(":"),
    (signal) =>
      imagesApi.pixels(
        projectId,
        asset.id,
        variant,
        // Unscaled images skip the backend's resize and re-encode.
        !largest || largest > LARGEST_SCALED ? LARGEST_SCALED : 0,
        () => !signal.aborted,
      ),
  );
  const canvas = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = canvas.current!;
    const observer = new ResizeObserver(([entry]) =>
      setBox({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const pixels = full.value ?? thumbnail;
  const width = full.value?.width || asset.width || pixels?.width || 0;
  const height = full.value?.height || asset.height || pixels?.height || 0;
  const scale =
    width && height ? Math.min(box.width / width, box.height / height) : 0;
  return (
    <>
      <div className="image-viewer-canvas" ref={canvas}>
        {full.error !== undefined ? (
          <span className="image-viewer-error">
            Preview unavailable. {messageOf(full.error)}
          </span>
        ) : pixels && scale ? (
          <img
            className="image-background-checker"
            src={pixels.url}
            alt={`Preview of ${asset.filename}`}
            // Game art scaled past its own pixels stays crisp, not blurred.
            data-crisp={
              (!!full.value && scale * devicePixelRatio > 1) || undefined
            }
            style={{ width: width * scale, height: height * scale }}
          />
        ) : (
          <ImageIcon size={24} aria-hidden="true" />
        )}
      </div>
      <figcaption className="image-viewer-caption">
        <FileName
          className="image-viewer-name"
          name={asset.filename}
          title={asset.path}
        />
        {!!width && (
          <span className="image-viewer-size">
            {width} × {height}
          </span>
        )}
        <span className="image-viewer-state" title={imageStatus(asset)}>
          <StatusMark state={imageDisplay(asset)} />
        </span>
        <Button variant="quiet" onClick={onCompare}>
          Compare
        </Button>
      </figcaption>
    </>
  );
}
