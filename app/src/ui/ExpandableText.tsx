import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Button } from "./Button";
import { tailExcerpt } from "./excerpt";

/** Show a readable excerpt while keeping the complete retained text available. */
export function ExpandableText({
  text,
  label,
  appearance = "code",
  truncate = true,
  fill = false,
  limit = 480,
  tail = false,
  lines = 0,
  lead,
}: {
  text: string;
  label: string;
  appearance?: "code" | "prose" | "inline";
  truncate?: boolean;
  fill?: boolean;
  limit?: number;
  /** Excerpt the end instead, for logs whose latest lines explain the outcome. */
  tail?: boolean;
  /** Inline text only: excerpt by rendered lines, so the height holds at every width. */
  lines?: number;
  /** Inline text only: reads in the same lines before the text, such as a status. */
  lead?: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const id = useId();
  const contentRef = useRef<HTMLElement>(null);
  const clamped = truncate && appearance === "inline" && lines > 0;
  // The lines the text fills are only known once it is laid out, and change
  // with the width.
  useLayoutEffect(() => {
    const element = contentRef.current;
    if (!clamped || expanded || !element) return;
    const measure = () =>
      setOverflowing(element.scrollHeight > element.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [clamped, expanded, text]);
  const content = text.trimEnd();
  const head = content.split("\n").slice(0, 6).join("\n").slice(0, limit);
  const excerpt = !truncate
    ? text
    : tail
      ? tailExcerpt(content, limit)
      : appearance === "code" || head.length === content.length
        ? head.trimEnd()
        : // Prose ends its excerpt between words.
          head.replace(/\s+\S*$/, "").trimEnd() || head.trimEnd();
  const shortened = clamped
    ? expanded || overflowing
    : truncate && excerpt.length < content.length;
  // Inline text reads within a sentence, such as a row's reason, so it
  // takes no block of its own.
  const Box = appearance === "inline" ? "span" : "div";
  const Content = appearance === "inline" ? "span" : "pre";
  // A collapsed excerpt's button floats into the last line's end, since text
  // after a clamped block would take a line of its own.
  const floated = clamped && !expanded;
  const button = (
    <Button
      variant="link"
      aria-label={`${expanded ? "Show less" : "Show more"}: ${label}`}
      aria-expanded={expanded}
      aria-controls={id}
      onClick={() => setExpanded((value) => !value)}
    >
      {expanded ? "Show less" : "Show more"}
    </Button>
  );
  return (
    <Box
      className={`expandable-text expandable-text--${appearance}${fill ? " expandable-text--fill" : ""}`}
    >
      <Content
        id={id}
        ref={contentRef as never}
        className={`expandable-text-content${clamped && !expanded ? " expandable-text-content--clamped" : ""}`}
        style={
          clamped && !expanded
            ? ({ "--excerpt-lines": lines } as React.CSSProperties)
            : undefined
        }
        role={fill ? "region" : undefined}
        tabIndex={fill ? 0 : undefined}
        aria-label={fill ? label : undefined}
      >
        {shortened && floated && button}
        {appearance === "inline" && lead}
        {clamped || !shortened || expanded
          ? text
          : tail
            ? "…\n" + excerpt
            : excerpt + "…"}
      </Content>
      {/* A space, unlike a margin, goes away where the button starts a line. */}
      {shortened && !floated && appearance === "inline" && " "}
      {shortened && !floated && button}
    </Box>
  );
}
