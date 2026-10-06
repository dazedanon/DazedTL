import { useState } from "react";
import type { ImageAsset } from "../../api/contracts";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import { Button } from "../../ui/Button";
import { DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { ActionBar } from "../../ui/ActionBar";
import { Message } from "../../ui/Feedback";
import { ExpandableText } from "../../ui/ExpandableText";
import { imageClassificationLabels, imageStatus } from "./imageSelection";
import { useRead } from "../../state/useRead";

export function ImageCompare({
  projectId,
  asset,
  busy,
  error,
  notice,
  onDismiss,
  onAction,
}: {
  projectId: string;
  asset: ImageAsset;
  busy: boolean;
  error: string;
  notice: string;
  onDismiss: () => void;
  onAction: (
    action: string,
    options?: Record<string, unknown>,
  ) => Promise<void>;
}) {
  const images = useRead(
    [projectId, asset.id, asset.sourceHash, asset.candidateHash].join(":"),
    (signal) =>
      Promise.all([
        imagesApi.pixels(
          projectId,
          asset.id,
          "original",
          0,
          () => !signal.aborted,
        ),
        asset.candidateHash
          ? imagesApi.pixels(
              projectId,
              asset.id,
              "candidate",
              0,
              () => !signal.aborted,
            )
          : Promise.resolve(null),
      ]),
  );
  const [source, candidate] = images.value ?? [null, null];
  const loadError = images.error === undefined ? "" : messageOf(images.error);
  const [zoom, setZoom] = useState(0);
  const [background, setBackground] = useState("checker");
  const [comment, setComment] = useState("");
  return (
    <Modal
      label={`Compare ${asset.filename}`}
      size="full"
      className="image-compare-modal"
      dismissible={!busy}
      onDismiss={onDismiss}
    >
      <DialogHeader
        title="Compare images"
        description={asset.path}
        onClose={onDismiss}
        closeDisabled={busy}
      />
      <div className="image-compare-toolbar">
        <span className="image-review-status">{imageStatus(asset)}</span>
        <label>
          Zoom
          <select
            aria-label="Image zoom"
            value={zoom}
            onChange={(event) => setZoom(Number(event.target.value))}
          >
            {[0, 0.25, 0.5, 1, 2, 4].map((value) => (
              <option key={value} value={value}>
                {value ? `${value * 100}%` : "Fit"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Background
          <select
            aria-label="Image background"
            value={background}
            onChange={(event) => setBackground(event.target.value)}
          >
            <option value="checker">Transparency</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
        </label>
      </div>
      <div className="image-compare-body">
        <Message message={loadError} />
        <div className="image-comparison">
          <figure>
            <figcaption>
              Original{" "}
              {source && (
                <span>
                  {source.width} × {source.height} · {source.mode}
                </span>
              )}
            </figcaption>
            <div
              className={`image-comparison-canvas image-background-${background}`}
            >
              {source ? (
                <img
                  src={source.url}
                  alt={`Original ${asset.filename}`}
                  style={
                    zoom
                      ? {
                          width: source.width * zoom,
                          height: source.height * zoom,
                        }
                      : { width: "100%", height: "100%" }
                  }
                />
              ) : (
                <p>Loading original…</p>
              )}
            </div>
          </figure>
          <figure>
            <figcaption>
              Edited{" "}
              {candidate && (
                <span>
                  {candidate.width} × {candidate.height} · {candidate.mode}
                </span>
              )}
            </figcaption>
            <div
              className={`image-comparison-canvas image-background-${background}`}
            >
              {candidate ? (
                <img
                  src={candidate.url}
                  alt={`Edited ${asset.filename}`}
                  style={
                    zoom
                      ? {
                          width: candidate.width * zoom,
                          height: candidate.height * zoom,
                        }
                      : { width: "100%", height: "100%" }
                  }
                />
              ) : (
                <p>
                  {asset.candidateHash
                    ? "Loading edited image…"
                    : "No edited copy yet."}
                </p>
              )}
            </div>
          </figure>
        </div>
        {asset.state === "blocked" || asset.sourceIssue ? (
          <Message message={asset.blockedReason || asset.sourceIssue || ""} />
        ) : asset.blockedReason ? (
          <p className="muted">{asset.blockedReason}</p>
        ) : null}
        {(asset.reason || (asset.aiReviewed && asset.reviewEvidence)) && (
          <dl className="image-evidence">
            {asset.reason && (
              <>
                <dt>Discovery</dt>
                <dd>
                  <ExpandableText
                    text={`${imageClassificationLabels[asset.classification] || asset.classification} · ${asset.reason}`}
                    label="Discovery finding"
                    appearance="inline"
                  />
                </dd>
              </>
            )}
            {asset.aiReviewed && asset.reviewEvidence && (
              <>
                <dt>AI review</dt>
                <dd>
                  <ExpandableText
                    text={asset.reviewEvidence}
                    label="AI review evidence"
                    appearance="inline"
                  />
                </dd>
              </>
            )}
          </dl>
        )}
        <label className="image-revision-comment">
          Revision notes
          <textarea
            aria-label="Image revision notes"
            rows={2}
            maxLength={4000}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Describe the change for your coding assistant…"
          />
        </label>
      </div>
      <ActionBar
        feedback={
          <>
            <Message message={error} />
            {notice && <span role="status">{notice}</span>}
          </>
        }
      >
        <Button
          disabled={busy}
          onClick={() =>
            onAction("revision_task", {
              asset_ids: [asset.id],
              comments: comment,
            })
          }
        >
          Copy revision task
        </Button>
        <Button
          disabled={busy || !candidate || asset.state === "blocked"}
          onClick={() =>
            onAction("user_review", {
              asset_ids: [asset.id],
              reason: comment,
              reviewed: !asset.userReviewed,
            })
          }
        >
          {asset.userReviewed ? "Remove user review" : "Mark user reviewed"}
        </Button>
      </ActionBar>
    </Modal>
  );
}
