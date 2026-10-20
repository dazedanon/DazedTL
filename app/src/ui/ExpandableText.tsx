import { useId, useState } from "react";
import { Button } from "./Button";

/** Show a readable excerpt while keeping the complete retained text available. */
export function ExpandableText({
  text,
  label,
  appearance = "code",
  truncate = true,
  fill = false,
  limit = 480,
  tail = false,
}: {
  text: string;
  label: string;
  appearance?: "code" | "prose" | "inline";
  truncate?: boolean;
  fill?: boolean;
  limit?: number;
  /** Excerpt the end instead, for logs whose latest lines explain the outcome. */
  tail?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const content = text.trimEnd();
  const head = content.split("\n").slice(0, 6).join("\n").slice(0, limit);
  const excerpt = !truncate
    ? text
    : tail
      ? content.split("\n").slice(-6).join("\n").slice(-limit)
      : appearance === "code" || head.length === content.length
        ? head.trimEnd()
        : // Prose ends its excerpt between words.
          head.replace(/\s+\S*$/, "").trimEnd() || head.trimEnd();
  const shortened = truncate && excerpt.length < content.length;
  // Inline text reads within a sentence, such as a row's reason, so it
  // takes no block of its own.
  const Box = appearance === "inline" ? "span" : "div";
  const Content = appearance === "inline" ? "span" : "pre";
  return (
    <Box
      className={`expandable-text expandable-text--${appearance}${fill ? " expandable-text--fill" : ""}`}
    >
      <Content
        id={id}
        className="expandable-text-content"
        role={fill ? "region" : undefined}
        tabIndex={fill ? 0 : undefined}
        aria-label={fill ? label : undefined}
      >
        {!shortened || expanded ? text : tail ? "…\n" + excerpt : excerpt + "…"}
      </Content>
      {/* A space, unlike a margin, goes away where the button starts a line. */}
      {shortened && appearance === "inline" && " "}
      {shortened && (
        <Button
          variant="link"
          aria-label={`${expanded ? "Show less" : "Show more"}: ${label}`}
          aria-expanded={expanded}
          aria-controls={id}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Show less" : "Show more"}
        </Button>
      )}
    </Box>
  );
}
