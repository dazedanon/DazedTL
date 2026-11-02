import { useState } from "react";
import { useLanguages } from "../../app/LanguagesProvider";
import type { ImageAsset } from "../../api/contracts";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import { Button } from "../../ui/Button";
import { DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { ActionBar } from "../../ui/ActionBar";
import { Message } from "../../ui/Feedback";
import { Notice } from "../../ui/Notice";
import { ExpandableText } from "../../ui/ExpandableText";
import { imageDisplay } from "../../ui/displayStatus";
import { StatusMark } from "../../ui/StatusMark";
import { imageDiscovery, imageReason, revisionEvent } from "./imageSelection";
import { useRead } from "../../state/useRead";
import { historyWhen } from "../guided/historyView";

export function ImageCompare({
  projectId,
  asset,
  listed,
  note,
  sentAt,
  onNote,
  busy,
  error,
  notice,
  onDismiss,
  onAction,
}: {
  projectId: string;
  asset: ImageAsset;
  /** Whether the image is in the list to translate. */
  listed: boolean;
  /** The image's revision note as the draft holds it. */
  note: string;
  /** When the copied task the assistant has now sent this note, if it did. */
  sentAt?: string;
  onNote: (text: string) => void;
  busy: boolean;
  error: string;
  notice: string;
  onDismiss: () => void;
  onAction: (
    action: string,
    options?: Record<string, unknown>,
  ) => Promise<void>;
}) {
  const { target } = useLanguages();
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
  const history = [...(asset.revisions || [])].reverse();
  const blocking = asset.state === "blocked" || !!asset.sourceIssue;
  const reasonShown = !blocking && !asset.heldReason;
  const reason = reasonShown && imageReason(asset, listed, target);
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
        {/* A blocking reason shows below the images, where it can be read
            as an error, and so does what holds the assistant's review, beside
            the actions that answer it; any other reason sits beside the state. */}
        <span className="image-review-status">
          <StatusMark state={imageDisplay(asset, listed)} />
          {reason && <span>{reason}</span>}
        </span>
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
        {blocking && (
          <Message message={asset.blockedReason || asset.sourceIssue || ""} />
        )}
        {!blocking && asset.heldReason && (
          <Notice tone="warning">{asset.heldReason}</Notice>
        )}
        {(asset.reason ||
          asset.skipReason ||
          (asset.aiReviewed && asset.reviewEvidence)) && (
          <dl className="image-evidence">
            {asset.reason && (
              <>
                <dt>Discovery</dt>
                <dd>
                  <ExpandableText
                    text={imageDiscovery(asset, listed, target, reasonShown)}
                    label="Discovery finding"
                    appearance="inline"
                  />
                </dd>
              </>
            )}
            {asset.skipReason && (
              <>
                <dt>Skipped</dt>
                <dd>
                  <ExpandableText
                    text={asset.skipReason}
                    label="Why the translation skipped it"
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
            value={note}
            onChange={(event) => onNote(event.target.value)}
            placeholder="Describe the change for your coding assistant…"
          />
          {note && (
            <small>
              {sentAt
                ? `Sent to your assistant ${historyWhen(sentAt)}. It stays here until its report answers it.`
                : "Kept with this image until your assistant's report answers it. Copy revision task in the Images footer sends every noted image at once."}
            </small>
          )}
        </label>
        {!!history.length && (
          <section className="image-revision-history">
            <h3>Revision history</h3>
            <ol>
              {history.map((entry, index) => (
                <li key={index}>
                  <span className="muted">
                    {revisionEvent(entry)}{" "}
                    {historyWhen(entry.answered || entry.saved)}
                  </span>
                  {entry.note && (
                    <ExpandableText
                      text={entry.note}
                      label="Revision note"
                      appearance="inline"
                    />
                  )}
                  {entry.reason && <span>{entry.reason}</span>}
                </li>
              ))}
            </ol>
          </section>
        )}
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
          onClick={() => onAction("revision_task", { asset_ids: [asset.id] })}
        >
          Copy revision task
        </Button>
        {/* A review binds the game's file, which Apply changed, so an image
            in the game has none to give until it is edited again. */}
        {asset.state !== "applied" && (
          <Button
            disabled={busy || !candidate || asset.state === "blocked"}
            onClick={() =>
              onAction("user_review", {
                asset_ids: [asset.id],
                reviewed: !asset.userReviewed,
              })
            }
          >
            {asset.userReviewed ? "Remove user review" : "Mark user reviewed"}
          </Button>
        )}
      </ActionBar>
    </Modal>
  );
}
