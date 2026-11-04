import type { DocumentDrafts, Documents } from "../api/contracts";
import { ActionBar } from "./ActionBar";
import { Button } from "./Button";
import { DialogBody, DialogHeader } from "./Dialog";
import { lineDiff } from "./lineDiff";
import { Modal } from "./Modal";
import { TextDiff } from "./TextDiff";

/**
 * The choice Save asks for when a document's file changed on disk after its
 * draft began, as an assistant changes it, in every method: keep the file,
 * discarding the draft, or keep the draft, saving it over the file. Each
 * document shows the draft compared with the file.
 */
export function DocumentsChangedDialog({
  documents,
  drafts,
  names,
  busy,
  keepFiles,
  keepDrafts,
  cancel,
}: {
  documents: Documents;
  drafts: DocumentDrafts;
  /** The documents whose file changed. */
  names: string[];
  busy: boolean;
  keepFiles: () => void;
  keepDrafts: () => void;
  cancel: () => void;
}) {
  const one = names.length === 1;
  const files = names.map((name) => documents[name].file);
  const titles = names.map((name) => documents[name].title);
  return (
    <Modal
      label="Changed on disk"
      size="sm"
      dismissible={!busy}
      onDismiss={cancel}
    >
      <DialogHeader
        title={
          one
            ? "Keep the file or your draft?"
            : "Keep the files or your drafts?"
        }
      />
      <DialogBody>
        <p>
          {files.join(", ")} changed on disk after you began editing the{" "}
          {titles.join(", ")}, as when an assistant edits {one ? "it" : "them"}.
        </p>
        {names.map((name) => (
          <section key={name}>
            <p className="muted">
              {one ? "Your draft" : `Your ${documents[name].title} draft`} (+)
              compared with the file (−):
            </p>
            <TextDiff
              diff={lineDiff(documents[name].text, drafts[name].text)}
              label={`Your ${documents[name].title} draft compared with ${documents[name].file}`}
            />
          </section>
        ))}
        <p className="muted">
          {one
            ? "Keeping your draft replaces the file. Keeping the file discards your draft."
            : "Keeping your drafts replaces the files. Keeping the files discards those drafts."}
        </p>
      </DialogBody>
      <ActionBar feedback={null}>
        <Button data-autofocus disabled={busy} onClick={cancel}>
          Cancel
        </Button>
        <Button disabled={busy} onClick={keepFiles}>
          {one ? "Keep the file" : "Keep the files"}
        </Button>
        <Button variant="primary" disabled={busy} onClick={keepDrafts}>
          {one ? "Keep my draft" : "Keep my drafts"}
        </Button>
      </ActionBar>
    </Modal>
  );
}
