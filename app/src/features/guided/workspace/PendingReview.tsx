import type {
  ImagePreview,
  PluginPreview,
  Preview,
} from "../../../api/contracts";
import { ActionBar } from "../../../ui/ActionBar";
import { Button } from "../../../ui/Button";
import { DialogBody, DialogHeader } from "../../../ui/Dialog";
import { Message } from "../../../ui/Feedback";
import { Modal } from "../../../ui/Modal";
import { StatusHeading } from "../../../ui/StatusMark";
import { ImageApplyContent } from "../../images/ImageApply";
import { PluginApplyContent } from "../../plugins/PluginApplyContent";
import { pendingSummary } from "../pending";
import { PublicationContent } from "../PublicationContent";
import type { PartReview, PendingChanges } from "./usePendingChanges";

/** One part's review content: the same as its own task's review. */
function PartContent({ part }: { part: PartReview }) {
  if (!part.preview) return null;
  if (part.id === "images")
    return <ImageApplyContent preview={part.preview as ImagePreview} />;
  if (part.id === "plugins")
    return <PluginApplyContent preview={part.preview as PluginPreview} />;
  return <PublicationContent preview={part.preview as Preview} />;
}

/**
 * Everything waiting to go into the game, in one review with one Apply. Each
 * part keeps its own review content; results appear beside each part.
 */
export function PendingReview({ pending }: { pending: PendingChanges }) {
  const parts = pending.review;
  if (!parts) return null;
  const ready = parts.filter((part) => part.state === "ready");
  const applied = parts.filter((part) => part.state === "applied");
  const busy = pending.busy && pending.key === "pending:apply";
  const retrying = pending.busy && pending.key === "pending:review";
  // After Apply, the dialog reports what went in and offers the rest again.
  const outcome = pending.attempted && !busy;
  const summary = pendingSummary(ready.length ? ready : parts);
  return (
    <Modal
      label="Review pending changes"
      size="lg"
      className="guided-sheet pending-review"
      dismissible={!pending.busy}
      onDismiss={pending.close}
    >
      <DialogHeader
        title={
          busy
            ? `Applying ${summary}`
            : outcome
              ? applied.length
                ? `Applied ${pendingSummary(applied)}`
                : "Nothing was applied"
              : `Apply ${summary}`
        }
        description={
          outcome
            ? "Parts that did not apply left the game unchanged."
            : "Backups of everything replaced are saved first, and each part can be restored on its own."
        }
      />
      <DialogBody>
        {parts.map((part, index) => (
          <details
            key={part.id}
            className="pending-part"
            // The first part opens; the rest stay closed until wanted.
            open={index === 0 && !!part.preview}
          >
            <summary>
              <StatusHeading
                state={part.state}
                pending={part.state === "working"}
                title={`${part.title} · ${part.summary}`}
              />
            </summary>
            {part.message &&
              (part.state === "blocked" ? (
                <Message message={part.message} />
              ) : (
                <p className="muted">{part.message}</p>
              ))}
            <PartContent part={part} />
          </details>
        ))}
      </DialogBody>
      <ActionBar
        feedback={
          <Message
            message={
              pending.key === "pending:apply" ||
              pending.key === "pending:review"
                ? pending.error
                : ""
            }
          />
        }
      >
        <Button disabled={pending.busy} onClick={pending.close}>
          {outcome ? "Close" : "Cancel"}
        </Button>
        {outcome && !!pending.remaining && (
          <Button
            variant="primary"
            pending={retrying}
            onClick={() => void pending.retry()}
          >
            Review again
          </Button>
        )}
        {!outcome && (
          <Button
            variant="primary"
            pending={busy}
            disabled={!ready.length && !busy}
            onClick={() => void pending.apply()}
          >
            {ready.length > 1 || parts.length > 1
              ? "Apply all"
              : `Apply ${summary}`}
          </Button>
        )}
      </ActionBar>
    </Modal>
  );
}
