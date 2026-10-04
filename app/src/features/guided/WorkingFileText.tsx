import { useEffect, useRef, useState } from "react";
import type { FileTextPreview } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";

export function WorkingFileText({ read }: { read: (offset: number, query: string, refresh: boolean) => Promise<FileTextPreview> }) {
  const [page, setPage] = useState<FileTextPreview | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [offsets, setOffsets] = useState([0]);
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const content = useRef<HTMLDivElement>(null);
  const readRefresh = useRef(0);
  const offset = offsets.at(-1)!;
  useEffect(() => {
    let current = true;
    setPending(true); setError("");
    const reread = refresh !== readRefresh.current;
    readRefresh.current = refresh;
    void read(offset, query, reread).then(value => { if (current) { setPage(value); content.current?.scrollTo(0, 0); } })
      .catch(value => { if (current) setError(value instanceof Error ? value.message : "Could not read this file."); })
      .finally(() => { if (current) setPending(false); });
    return () => { current = false; };
  }, [read, offset, query, refresh]);
  const comparison = page?.rows.some(row => row.source != null);
  return <div className="working-file-text">
    <form className="file-text-tools" onSubmit={event => { event.preventDefault(); setQuery(search); setOffsets([0]); }}>
      <input type="search" aria-label="Find text in this file" placeholder="Find text or field…" value={search} onChange={event => setSearch(event.target.value)} />
      <Button type="submit" disabled={pending}>Find</Button><Button variant="quiet" pending={pending} onClick={() => { setOffsets([0]); setRefresh(value => value + 1); }}>Refresh text</Button>
    </form>
    <Message message={error} />
    {page && <div className="file-text-caption"><span>{{ translated: "Saved output", working: "Working input", game: "Game file" }[page.origin]} · read-only</span><span>{page.total ? `${page.offset + 1}–${page.offset + page.rows.length} of ${page.total} fields` : "0 fields"}</span></div>}
    {!page && !error && <p role="status">Reading file text…</p>}
    <div className="file-text-content" ref={content} tabIndex={0} aria-label="Working file text" aria-busy={pending}>
      {page && !page.rows.length ? <p className="muted">{query ? "No text fields match this search." : "This file has no non-empty text fields."}</p> : page && <table className="translation-comparison file-text-table">
        <thead><tr>{comparison && <th>Source text</th>}<th>{page.origin === "translated" ? "Saved text" : "Current text"}</th></tr></thead><tbody>
          {page.rows.map((row, index) => <tr key={page.offset + index}>{comparison && <td>{row.source ?? <span className="muted" title="No different source text retained">—</span>}</td>}<td><small>{row.location}</small>{row.text}{row.truncated && <small>Long field shortened for display.</small>}</td></tr>)}
        </tbody></table>}
    </div>
    <div className="file-text-pages"><small>File contents; the estimate determines which fields will be translated.</small>
      {page && (page.nextOffset != null || offsets.length > 1) && <div><Button variant="quiet" disabled={pending || offsets.length < 2} onClick={() => setOffsets(previous => previous.slice(0, -1))}>Previous</Button><Button variant="quiet" disabled={pending || page.nextOffset == null} onClick={() => setOffsets(previous => [...previous, page.nextOffset!])}>Next</Button></div>}
    </div>
  </div>;
}
