import { useId, useState } from "react";
import { Button } from "./Button";

/** Show a readable excerpt while keeping the complete retained text available. */
export function ExpandableText({ text, label, appearance = "code", truncate = true, fill = false, limit = 480 }: { text: string; label: string; appearance?: "code" | "prose" | "inline"; truncate?: boolean; fill?: boolean; limit?: number }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const excerpt = truncate ? text.split("\n").slice(0, 6).join("\n").slice(0, limit).trimEnd() : text;
  const shortened = truncate && excerpt.length < text.trimEnd().length;
  return <div className={`expandable-text expandable-text--${appearance}${fill ? " expandable-text--fill" : ""}`}>
    <pre id={id} className="expandable-text-content" role={fill ? "region" : undefined} tabIndex={fill ? 0 : undefined} aria-label={fill ? label : undefined}>{shortened && !expanded ? excerpt + "…" : text}</pre>
    {shortened && <Button variant="link" aria-label={`${expanded ? "Show less" : "Show more"}: ${label}`} aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(value => !value)}>{expanded ? "Show less" : "Show more"}</Button>}
  </div>;
}
