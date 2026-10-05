import { useEffect, useRef, useState } from "react";
import { LoaderCircle } from "lucide-react";
import type { NameTranslation, NameTranslationPage } from "../../api/contracts";
import { messageOf } from "../../api/errors";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";

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
  const reader = useRef(read);
  reader.current = read;
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<NameTranslationPage | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let current = true;
    setPending(true);
    setError("");
    setPage(null);
    void reader
      .current(offset)
      .then((value) => {
        if (current) setPage(value);
      })
      .catch((failure) => {
        if (current) setError(messageOf(failure));
      })
      .finally(() => {
        if (current) setPending(false);
      });
    return () => {
      current = false;
    };
  }, [offset, retry]);
  return (
    <Modal
      label="Translated names and labels"
      className="guided-sheet translation-review"
      onDismiss={close}
    >
      <header className="guided-sheet-heading">
        <h2>Translated names and labels</h2>
      </header>
      <div className="guided-sheet-body">
        <p className="muted">
          Saved in this run’s glossary for the file translation. These entries
          let you review the wording.
        </p>
        {pending ? (
          <p role="status">Reading saved translations…</p>
        ) : error ? (
          <>
            <Message message={error} />
            <Button onClick={() => setRetry((value) => value + 1)}>
              Try again
            </Button>
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
      </div>
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
              disabled={pending || offset === 0}
              onClick={() => setOffset((value) => Math.max(0, value - 50))}
            >
              Previous
            </Button>
            <Button
              disabled={pending || page.nextOffset == null}
              onClick={() => setOffset(page.nextOffset!)}
            >
              Next
            </Button>
          </>
        )}
        <Button onClick={close}>Close</Button>
      </ActionBar>
    </Modal>
  );
}
