import { useState } from "react";
import { LoaderCircle } from "lucide-react";
import type { NameTranslation, NameTranslationPage } from "../../api/contracts";
import { messageOf } from "../../api/errors";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { useRead } from "../../state/useRead";

type Reader = (offset: number) => Promise<NameTranslationPage>;

export function NameTranslationFeedback({
  value,
  read,
}: {
  value?: NameTranslation | null;
  read?: Reader;
}) {
  const [open, setOpen] = useState(false);
  if (!value) return null;
  const saved = value.state === "saved";
  return (
    <section
      className="name-translation-feedback"
      aria-label="Name translation result"
    >
      <span
        role="status"
        className={
          !saved && value.state !== "running" ? "translation-error" : undefined
        }
      >
        {value.state === "running" && (
          <LoaderCircle
            size={14}
            className="job-status-spinner"
            aria-hidden="true"
          />
        )}
        {saved
          ? value.reused
            ? "Using saved names and labels"
            : "Names and labels saved"
          : value.state === "running"
            ? "Translating names and labels…"
            : value.state === "failed"
              ? "Name translation did not finish"
              : "Name translation result unavailable"}
      </span>
      {saved && read && (
        <Button variant="link" onClick={() => setOpen(true)}>
          View {value.count}{" "}
          {value.count === 1 ? "translation" : "translations"}
        </Button>
      )}
      {!saved && value.state !== "running" && (
        <span>Check this run’s log before retrying paid work.</span>
      )}
      {open && read && <NameResults read={read} close={() => setOpen(false)} />}
    </section>
  );
}

function NameResults({ read, close }: { read: Reader; close: () => void }) {
  const [offset, setOffset] = useState(0);
  const names = useRead(String(offset), () => read(offset));
  const page = names.value;
  const error = names.error === undefined ? "" : messageOf(names.error);
  return (
    <Modal
      label="Translated names and labels"
      size="md"
      className="guided-sheet translation-review"
      onDismiss={close}
    >
      <DialogHeader
        title="Translated names and labels"
        description="Saved in this run’s glossary for the file translation. These entries let you review the wording."
        onClose={close}
      />
      <DialogBody>
        {names.pending ? (
          <p role="status">Reading saved translations…</p>
        ) : error ? (
          <>
            <Message message={error} />
            <Button onClick={names.retry}>Try again</Button>
          </>
        ) : (
          page && (
            <table className="translation-comparison">
              <thead>
                <tr>
                  <th>Original</th>
                  <th>Translation</th>
                </tr>
              </thead>
              <tbody>
                {page.rows.map((row) => (
                  <tr key={row.source}>
                    <td>{row.source}</td>
                    <td>{row.translation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </DialogBody>
      <ActionBar
        feedback={
          page && page.total > 50 ? (
            <small>
              {page.offset + 1}–{page.offset + page.rows.length} of {page.total}
            </small>
          ) : null
        }
      >
        {page && page.total > 50 && (
          <>
            <Button
              disabled={names.pending || offset === 0}
              onClick={() => setOffset((value) => Math.max(0, value - 50))}
            >
              Previous
            </Button>
            <Button
              disabled={names.pending || page.nextOffset == null}
              onClick={() => setOffset(page.nextOffset!)}
            >
              Next
            </Button>
          </>
        )}
      </ActionBar>
    </Modal>
  );
}
