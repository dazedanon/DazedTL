import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ExternalLink } from "lucide-react";
import type { Token, Tokens } from "marked";
import { useAction } from "../../state/useAction";
import { useRead } from "../../state/useRead";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import {
  PageBody,
  PageHeader,
  PageLayout,
  PageMessages,
} from "../../ui/PageLayout";
import { messageOf } from "../../api/errors";
import {
  parseGuide,
  plainText,
  searchGuide,
  type GuideDocument,
} from "./guideDocument";

/** Element IDs carry a prefix, so a section can't share one with the app. */
const elementId = (anchor: string) => "guide-" + anchor;

type Links = {
  anchors: GuideDocument["anchors"];
  jump: (anchor: string) => void;
  open: (href: string) => void;
};

function GuideImage({ source, alt }: { source: string; alt: string }) {
  const image = useRead(source, () => window.dazedtl.guide.image(source));
  if (image.error) return <span className="muted">{alt}</span>;
  return image.value ? (
    <img className="guide-image" src={image.value} alt={alt} />
  ) : null;
}

function inline(tokens: readonly Token[] = [], links: Links): ReactNode[] {
  return tokens.map((token, index) => {
    switch (token.type) {
      case "strong":
        return <strong key={index}>{inline(token.tokens, links)}</strong>;
      case "em":
        return <em key={index}>{inline(token.tokens, links)}</em>;
      case "del":
        return <del key={index}>{inline(token.tokens, links)}</del>;
      case "codespan":
        return <code key={index}>{token.text}</code>;
      case "br":
        return <br key={index} />;
      case "image":
        return <GuideImage key={index} source={token.href} alt={token.text} />;
      case "link": {
        const href: string = token.href;
        const label = inline(token.tokens, links);
        // Links to a section move within the page; the rest leave the app.
        return href.startsWith("#") ? (
          <a
            key={index}
            href={href}
            onClick={(event) => {
              event.preventDefault();
              links.jump(decodeURIComponent(href.slice(1)));
            }}
          >
            {label}
          </a>
        ) : (
          <a
            key={index}
            href={href}
            title={href.startsWith("https:") ? href : undefined}
            onClick={(event) => {
              event.preventDefault();
              links.open(href);
            }}
          >
            {label}
            {/* A word joiner keeps the mark on the link's last line. */}
            {"\u2060"}
            <ExternalLink
              size={12}
              className="guide-external"
              aria-hidden="true"
            />
            <span className="sr-only"> (opens in your browser)</span>
          </a>
        );
      }
      default:
        return "tokens" in token && token.tokens
          ? inline(token.tokens, links)
          : plainText([token]);
    }
  });
}

function blocks(tokens: readonly Token[], links: Links): ReactNode[] {
  return tokens.map((token, index) => {
    switch (token.type) {
      case "heading": {
        const Heading = (["h2", "h3", "h4"] as const)[
          Math.min(Math.max(token.depth, 2), 4) - 2
        ];
        const anchor = links.anchors.get(token);
        return (
          <Heading key={index} id={anchor && elementId(anchor)}>
            {inline(token.tokens, links)}
          </Heading>
        );
      }
      case "paragraph":
        return <p key={index}>{inline(token.tokens, links)}</p>;
      case "text":
        // A tight list item's text, which takes no paragraph.
        return inline(token.tokens ?? [token], links);
      case "list": {
        const items = (token as Tokens.List).items.map((item, number) => (
          <li key={number}>{blocks(item.tokens, links)}</li>
        ));
        return token.ordered ? (
          <ol key={index} start={token.start === 1 ? undefined : token.start}>
            {items}
          </ol>
        ) : (
          <ul key={index}>{items}</ul>
        );
      }
      case "table": {
        const table = token as Tokens.Table;
        return (
          <div key={index} className="guide-table">
            <table>
              <thead>
                <tr>
                  {table.header.map((cell, column) => (
                    <th key={column} data-align={cell.align ?? undefined}>
                      {inline(cell.tokens, links)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, number) => (
                  <tr key={number}>
                    {row.map((cell, column) => (
                      <td key={column} data-align={cell.align ?? undefined}>
                        {inline(cell.tokens, links)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      case "code":
        return (
          <pre key={index} className="guide-code">
            <code>{token.text}</code>
          </pre>
        );
      case "blockquote":
        return (
          <blockquote key={index}>
            {blocks(token.tokens ?? [], links)}
          </blockquote>
        );
      case "hr":
        return <hr key={index} />;
      // Space between blocks, and HTML such as comments, show nothing.
      case "space":
      case "html":
        return null;
      default:
        return <p key={index}>{plainText([token])}</p>;
    }
  });
}

/** Markdown, as the guide's own components draw it. */
function Markdown({
  tokens,
  links,
  inline: inLine = false,
}: {
  tokens: readonly Token[];
  links: Links;
  /** Text inside a block, such as a paragraph's. */
  inline?: boolean;
}) {
  return inLine ? inline(tokens, links) : blocks(tokens, links);
}

/**
 * The user guide, read from docs/user-guide.md in this install: its sections
 * beside the text, a search that narrows them, and a section to open at,
 * such as one a help popover's Learn more names.
 */
export default function Guide({
  visible,
  request,
}: {
  visible: boolean;
  /** A section to open at; each new request opens it again. */
  request?: { section?: string };
}) {
  const read = useRead("guide", () => window.dazedtl.guide.read());
  const guide = useMemo(
    () => (read.value === undefined ? null : parseGuide(read.value)),
    [read.value],
  );
  const sections = useMemo(
    () => guide?.headings.filter((heading) => heading.depth <= 3) ?? [],
    [guide],
  );
  const action = useAction();
  const body = useRef<HTMLDivElement>(null);
  const nav = useRef<HTMLUListElement>(null);
  const [query, setQuery] = useState("");
  const [current, setCurrent] = useState<string>();
  // A section opened near the end of the page can't reach its top, so it
  // stays current until the page scrolls away from the end.
  const opened = useRef<string>(undefined);
  const shown = query.trim()
    ? searchGuide(sections, query)
    : sections.map((section) => ({ ...section, match: true }));
  const highlighted = current ?? sections[0]?.id;

  const jump = (anchor: string) => {
    const box = body.current;
    const target = document.getElementById(elementId(anchor));
    if (!box || !target) return;
    opened.current = anchor;
    setCurrent(anchor);
    box.scrollTop +=
      target.getBoundingClientRect().top -
      box.getBoundingClientRect().top -
      parseFloat(getComputedStyle(box).paddingTop);
  };
  const follow = () => {
    const box = body.current;
    if (!box || !sections.length) return;
    const line =
      box.getBoundingClientRect().top +
      parseFloat(getComputedStyle(box).paddingTop) +
      24;
    let found = sections[0].id;
    for (const section of sections) {
      const heading = document.getElementById(elementId(section.id));
      if (!heading || heading.getBoundingClientRect().top > line) break;
      found = section.id;
    }
    if (box.scrollTop + box.clientHeight < box.scrollHeight - 1)
      opened.current = undefined;
    setCurrent(opened.current ?? found);
  };
  // The current section stays in view in a list taller than the window.
  useEffect(() => {
    const list = nav.current;
    const item = list?.querySelector<HTMLElement>("[aria-current]");
    if (!list || !item) return;
    if (item.offsetTop < list.scrollTop) list.scrollTop = item.offsetTop;
    else if (
      item.offsetTop + item.offsetHeight >
      list.scrollTop + list.clientHeight
    )
      list.scrollTop = item.offsetTop + item.offsetHeight - list.clientHeight;
  }, [highlighted]);
  // A requested section opens once the page shows, since a hidden page has
  // no layout to scroll.
  const handled = useRef<object>(undefined);
  useEffect(() => {
    if (!visible || !guide || !request || handled.current === request) return;
    handled.current = request;
    if (request.section) jump(request.section);
  });

  const links: Links = {
    anchors: guide?.anchors ?? new Map(),
    jump,
    // Each click opens its own link; only a failure shows.
    open: (href) => {
      action.clear();
      window.dazedtl.guide.open(href).catch(action.report);
    },
  };
  const intro = guide?.intro.flatMap((token, index) =>
    token.type === "paragraph"
      ? [
          <Markdown
            key={index}
            tokens={token.tokens ?? []}
            links={links}
            inline
          />,
        ]
      : [],
  );
  return (
    <PageLayout variant="editor" className="guide-page" aria-label="Guide">
      <PageHeader
        title="Guide"
        description={intro?.length ? intro : undefined}
      />
      <PageMessages>
        <Message message={action.error} onDismiss={action.clear} />
      </PageMessages>
      <PageBody ref={body} className="guide-body" onScroll={follow}>
        {read.error ? (
          <div className="guide-problem">
            <p>The guide could not be read. {messageOf(read.error)}</p>
            <Button onClick={read.retry}>Try again</Button>
          </div>
        ) : !guide ? (
          <p className="muted">Opening the guide…</p>
        ) : (
          <div className="guide-layout">
            <nav className="guide-nav" aria-label="Guide sections">
              <input
                type="search"
                aria-label="Search the guide"
                placeholder="Search the guide…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  const first = shown.find((section) => section.match);
                  if (event.key === "Enter" && first) jump(first.id);
                }}
              />
              {shown.length ? (
                <ul ref={nav}>
                  {shown.map((section) => (
                    <li
                      key={section.id}
                      data-depth={section.depth}
                      data-match={section.match || undefined}
                    >
                      <button
                        type="button"
                        aria-current={
                          section.id === highlighted ? "location" : undefined
                        }
                        onClick={() => jump(section.id)}
                      >
                        {section.title}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No section mentions “{query.trim()}”.</p>
              )}
            </nav>
            <article className="guide-article">
              <Markdown tokens={guide.body} links={links} />
            </article>
          </div>
        )}
      </PageBody>
    </PageLayout>
  );
}
