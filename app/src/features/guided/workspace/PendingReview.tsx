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
import { ImageApplyContent } from "../../images/ImageApply";
import { PluginApplyContent } from "../../plugins/PluginApplyContent";
import { PublicationContent } from "../PublicationContent";
import type { PartReview, PendingChanges } from "./usePendingChanges";

/** A part's review content: the same as its own task's review. */
function PartContent({ part }: { part: PartReview }) {
  if (part.id === "images")
    return <ImageApplyContent preview={part.preview as ImagePreview} />;
  if (part.id === "plugins")
    return <PluginApplyContent preview={part.preview as PluginPreview} />;
  return <PublicationContent preview={part.preview as Preview} />;
}

/** The review and Apply of what a task has ready to go into the game. */
export function PendingReview({ pending }: { pending: PendingChanges }) {
  const part = pending.review;
  if (!part) return null;
  const busy = pending.busy && pending.key === "pending:apply";
  const retrying = pending.busy && pending.key === "pending:review";
  return (
    <Modal
      label={`Apply ${part.title.toLowerCase()}`}
      size="lg"
      className="guided-sheet"
      dismissible={!pending.busy}
      onDismiss={pending.close}
    >
      <DialogHeader
        title={
          busy
            ? `Applying ${part.summary}`
            : part.failure
              ? "Nothing was applied"
              : `Apply ${part.summary}`
        }
        // Each part's own content says how it backs up what it replaces.
        description={part.failure && "The game was left unchanged."}
      />
      <DialogBody>
        <Message message={part.failure} />
        <PartContent part={part} />
      </DialogBody>
      <ActionBar
        feedback={
          <Message
            message={pending.key === "pending:review" ? pending.error : ""}
          />
        }
      >
        <Button disabled={pending.busy} onClick={pending.close}>
          {part.failure ? "Close" : "Cancel"}
        </Button>
        {part.failure ? (
          <Button
            variant="primary"
            pending={retrying}
            onClick={() => void pending.retry()}
          >
            Review again
          </Button>
        ) : (
          <Button
            variant="primary"
            pending={busy}
            onClick={() => void pending.apply()}
          >
            Apply {part.summary}
          </Button>
        )}
      </ActionBar>
    </Modal>
  );
}
