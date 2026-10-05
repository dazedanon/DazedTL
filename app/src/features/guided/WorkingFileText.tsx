import { useEffect, useRef, useState } from "react";
import type { FileTextPreview } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { HelpPopover } from "../../ui/HelpPopover";
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";

export function WorkingFileText({
  source,
  read,
}: {
  /** Identifies what `read` reads; a new source reads again from the start. */
  source: string;
  read: (
    offset: number,
    query: string,
    refresh: boolean,
  ) => Promise<FileTextPreview>;
}) {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [offsets, setOffsets] = useState([0]);
  const [refresh, setRefresh] = useState(0);
  const content = useRef<HTMLDivElement>(null);
  const readRefresh = useRef(0);
  const offset = offsets.at(-1)!;
  const text = useRead([source, offset, query, refresh].join(":"), () => {
    const reread = refresh !== readRefresh.current;
    readRefresh.current = refresh;
    return read(offset, query, reread);
  });
  // The current page stays visible while the next one loads.
  const [page, setPage] = useState<FileTextPreview | null>(null);
  useOnChange(text.value, (value) => {
    if (value) setPage(value);
  });
  useEffect(() => {
    if (text.value) content.current?.scrollTo(0, 0);
  }, [text.value]);
  const pending = text.pending;
  const error =
    text.error === undefined
      ? ""
      : text.error instanceof Error
        ? text.error.message
        : "Could not read this file.";
  const comparison = page?.rows.some((row) => row.source != null);
  return (
    <div className="working-file-text">
      <form
        className="file-text-tools"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(search);
          setOffsets([0]);
        }}
      >
        <input
          type="search"
          aria-label="Find text in this file"
          placeholder="Find text or field…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Button type="submit" disabled={pending}>
          Find
        </Button>
        <Button
          variant="quiet"
          pending={pending}
          onClick={() => {
            setOffsets([0]);
            setRefresh((value) => value + 1);
          }}
        >
          Refresh text
        </Button>
      </form>
      <Message message={error} />
      {!page && !error && <p role="status">Reading file text…</p>}
      <div
        className="file-text-content"
        ref={content}
        tabIndex={0}
        aria-label="Working file text"
        aria-busy={pending}
      >
        {page && !page.rows.length ? (
          <p className="muted">
            {query
              ? "No text fields match this search."
              : "No changed or unmatched text fields to show."}
          </p>
        ) : (
          page && (
            <table className="translation-comparison file-text-table">
              <thead>
                <tr>
                  {comparison && <th>Source text</th>}
                  <th>
                    {page.origin === "translated"
                      ? "Saved text"
                      : "Current text"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.rows.map((row, index) => (
                  <tr key={page.offset + index}>
                    {comparison && (
                      <td>
                        {row.source ?? (
                          <span
                            className="muted"
                            title="No different source text retained"
                          >
                            -
                          </span>
                        )}
                      </td>
                    )}
                    <td>
                      <small>{row.location}</small>
                      {row.text}
                      {row.truncated && (
                        <small>Long field shortened for display.</small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
      <div className="file-text-pages">
        <div className="file-text-origin">
          {page && (
            <span>
              {
                {
                  translated: "Saved output",
                  working: "Working input",
                  game: "Game file",
                }[page.origin]
              }{" "}
              · read-only
            </span>
          )}
          <HelpPopover label="File contents">
            Unchanged fields are hidden when source text is available. The
            estimate determines which fields will be translated.
          </HelpPopover>
        </div>
        {page && page.total > 0 && (
          <span>
            {page.offset + 1}–{page.offset + page.rows.length} of{" "}
            {page.total.toLocaleString()} fields
          </span>
        )}
        {page && (page.nextOffset != null || offsets.length > 1) && (
          <div>
            <Button
              variant="quiet"
              disabled={pending || offsets.length < 2}
              onClick={() => setOffsets((previous) => previous.slice(0, -1))}
            >
              Previous
            </Button>
            <Button
              variant="quiet"
              disabled={pending || page.nextOffset == null}
              onClick={() =>
                setOffsets((previous) => [...previous, page.nextOffset!])
              }
            >
              Next
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
