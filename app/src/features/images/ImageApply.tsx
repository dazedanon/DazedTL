import { useState } from "react";
import type { ImagePreview } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { ActionBar } from "../../ui/ActionBar";
import { Message } from "../../ui/Feedback";

/** What an image apply or restore includes and leaves out. */
export function ImageApplyContent({
  preview,
  selected,
}: {
  preview: ImagePreview;
  /** How many images were chosen, when it can differ from the included. */
  selected?: number;
}) {
  const restore = preview.action.includes("restore");
  const count =
    typeof preview.included === "number"
      ? preview.included
      : preview.assets.length;
  const [page, setPage] = useState(0);
  const [blockedPage, setBlockedPage] = useState(0);
  const [copyNotice, setCopyNotice] = useState("");
  const pageSize = 50;
  const included = preview.assets.slice(page * pageSize, (page + 1) * pageSize);
  const blocked = preview.blocked.slice(
    blockedPage * pageSize,
    (blockedPage + 1) * pageSize,
  );
  return (
    <>
      {/* The title gives the count; the line explains only a difference
          from the selection. */}
      {((selected !== undefined && selected !== count) ||
        !!preview.blocked.length ||
        !!preview.unchanged) && (
        <p>
          <strong>
            {[
              selected !== undefined && `${selected} selected`,
              `${count} included`,
              preview.blocked.length && `${preview.blocked.length} blocked`,
              preview.unchanged && `${preview.unchanged} unchanged`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </strong>
        </p>
      )}
      <p>
        {restore
          ? "Verified backups replace these runtime assets. Editable copies remain available."
          : "Originals are backed up. Source files and edited images are validated again, and nothing is applied unless every included image passes."}
      </p>
      <div
        className="image-apply-files"
        aria-label="Included runtime destinations"
      >
        <h3>Included destinations</h3>
        {included.map((asset) => (
          <div key={asset.id}>
            <strong>{asset.path}</strong>
            {asset.destination !== asset.path && (
              <span>{asset.destination}</span>
            )}
          </div>
        ))}
        {!count && (
          <p>
            No images can be included. Return to the manager and resolve the
            issues.
          </p>
        )}
        {preview.assets.length > pageSize && (
          <div className="image-apply-pagination">
            <span>
              {page * pageSize + 1}–
              {Math.min((page + 1) * pageSize, preview.assets.length)} of{" "}
              {preview.assets.length} destinations
            </span>
            <Button disabled={!page} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <Button
              disabled={(page + 1) * pageSize >= preview.assets.length}
              onClick={() => setPage(page + 1)}
            >
              Next
            </Button>
          </div>
        )}
        <Button
          variant="link"
          onClick={() => {
            void window.dazedtl
              .copyText(
                preview.assets
                  .map((asset) => asset.path + "\n  " + asset.destination)
                  .join("\n"),
              )
              .then(
                () => setCopyNotice("Destination list copied."),
                () =>
                  setCopyNotice(
                    "Could not copy the list. The destinations remain available here.",
                  ),
              );
          }}
        >
          Copy destination list
        </Button>
        {copyNotice && <span role="status">{copyNotice}</span>}
      </div>
      {!!preview.blocked.length && (
        <section className="image-apply-blocked">
          <h3>Blocked images remain excluded</h3>
          {blocked.map((asset) => (
            <p key={asset.id}>
              <strong>{asset.path}</strong>
              <span>{asset.reason}</span>
            </p>
          ))}
          {preview.blocked.length > pageSize && (
            <div className="image-apply-pagination">
              <span>
                {blockedPage * pageSize + 1}–
                {Math.min((blockedPage + 1) * pageSize, preview.blocked.length)}{" "}
                of {preview.blocked.length} blocked images
              </span>
              <Button
                disabled={!blockedPage}
                onClick={() => setBlockedPage(blockedPage - 1)}
              >
                Previous blocked
              </Button>
              <Button
                disabled={
                  (blockedPage + 1) * pageSize >= preview.blocked.length
                }
                onClick={() => setBlockedPage(blockedPage + 1)}
              >
                Next blocked
              </Button>
            </div>
          )}
        </section>
      )}
    </>
  );
}

export function ImageApply({
  preview,
  selected,
  busy,
  error,
  onDismiss,
  onConfirm,
}: {
  preview: ImagePreview;
  selected: number;
  busy: boolean;
  error: string;
  onDismiss: () => void;
  onConfirm: () => void;
}) {
  const restore = preview.action.includes("restore");
  const count =
    typeof preview.included === "number"
      ? preview.included
      : preview.assets.length;
  const images = count === 1 ? "image" : "images";
  return (
    <Modal
      label={restore ? "Restore image originals" : "Review image application"}
      size="md"
      className="image-apply-modal"
      dismissible={!busy}
      onDismiss={onDismiss}
    >
      <DialogHeader
        title={
          restore
            ? `Restore ${count} original ${images}`
            : `Apply ${count} ${images} to the game`
        }
      />
      <DialogBody className="image-apply-body">
        <ImageApplyContent preview={preview} selected={selected} />
      </DialogBody>
      <ActionBar feedback={<Message message={error} />}>
        <Button disabled={busy} onClick={onDismiss}>
          Cancel
        </Button>
        <Button
          variant="primary"
          pending={busy}
          disabled={!count}
          onClick={onConfirm}
        >
          {restore ? `Restore ${count} ${images}` : `Apply ${count} ${images}`}
        </Button>
      </ActionBar>
    </Modal>
  );
}
