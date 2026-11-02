import GithubSlugger from "github-slugger";
import { Lexer, type Token } from "marked";

/**
 * A heading of the guide. Its anchor is the one GitHub gives it, so a link
 * such as `#checkpoints-and-undo` opens the same place in the app and on the
 * forge.
 */
export type GuideHeading = {
  id: string;
  depth: number;
  title: string;
  /** The anchor of the section a subsection belongs to. */
  parent?: string;
  /** Its title and text up to the next heading, in lower case for search. */
  search: string;
};
export type GuideDocument = {
  title: string;
  /** What comes before the first section. */
  intro: Token[];
  body: Token[];
  headings: GuideHeading[];
  anchors: Map<Token, string>;
};

/** The text a reader sees in tokens, without its markup. */
export function plainText(tokens: readonly Token[] = []): string {
  return tokens
    .map((token) => {
      if ("tokens" in token && token.tokens) return plainText(token.tokens);
      switch (token.type) {
        case "list":
          return token.items
            .map((item: { tokens: Token[] }) => plainText(item.tokens))
            .join(" ");
        case "table":
          return [token.header, ...token.rows]
            .flat()
            .map((cell: { tokens: Token[] }) => plainText(cell.tokens))
            .join(" ");
        case "space":
        case "hr":
        case "html":
          return " ";
        default:
          return "text" in token ? String(token.text) : "";
      }
    })
    .join("");
}

/**
 * The guide's Markdown in blocks, with an anchor for every heading. The
 * first top-level heading is the guide's title, and what follows it until
 * the first section is its introduction.
 */
export function parseGuide(source: string): GuideDocument {
  const slugger = new GithubSlugger();
  const document: GuideDocument = {
    title: "",
    intro: [],
    body: [],
    headings: [],
    anchors: new Map(),
  };
  let parent: string | undefined;
  for (const token of new Lexer({ gfm: true }).lex(source)) {
    const current = document.headings.at(-1);
    if (token.type !== "heading") {
      if (current) {
        document.body.push(token);
        current.search += " " + plainText([token]).toLowerCase();
      } else document.intro.push(token);
      continue;
    }
    const title = plainText(token.tokens);
    // GitHub numbers repeated titles in document order, the title included.
    const id = slugger.slug(title);
    if (token.depth === 1 && !document.title && !current) {
      document.title = title;
      continue;
    }
    if (token.depth <= 2) parent = id;
    document.anchors.set(token, id);
    document.body.push(token);
    document.headings.push({
      id,
      depth: token.depth,
      title,
      parent: token.depth > 2 ? parent : undefined,
      search: title.toLowerCase(),
    });
  }
  return document;
}

/**
 * The headings a search shows: those whose section mentions every word, as
 * matches, and the section each such subsection belongs to.
 */
export function searchGuide(headings: readonly GuideHeading[], query: string) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const found = new Set(
    headings
      .filter((heading) => words.every((word) => heading.search.includes(word)))
      .map((heading) => heading.id),
  );
  const parents = new Set(
    headings
      .filter((heading) => found.has(heading.id) && heading.parent)
      .map((heading) => heading.parent),
  );
  return headings.flatMap((heading) =>
    found.has(heading.id) || parents.has(heading.id)
      ? [{ ...heading, match: found.has(heading.id) }]
      : [],
  );
}
