import { useId, useState } from "react";
import { Button } from "./Button";

/** Show a readable excerpt while keeping the complete retained text available. */
export function ExpandableText({ text, label }: { text: string; label: string }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const excerpt = text.split("\n").slice(0, 6).join("\n").slice(0, 480).trimEnd();
  const shortened = excerpt.length < text.trimEnd().length;
  return <div className="expandable-text">
    <pre id={id}>{shortened && !expanded ? excerpt + "…" : text}</pre>
    {shortened && <Button variant="quiet" aria-label={`${expanded ? "Show less" : "Show more"}: ${label}`} aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(value => !value)}>{expanded ? "Show less" : "Show more"}</Button>}
  </div>;
}
