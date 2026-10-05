import type { RunPayload } from "../../api/contracts";
import { ExpandableText } from "../../ui/ExpandableText";
import { requestContext } from "./translationView";

function ContextSection({ title, text, compact }: { title: string; text: string; compact: boolean }) {
  return <section className="translation-matched-context">
    <h3>{title}</h3>
    <ExpandableText text={text} label={title} appearance="prose" truncate={compact} />
  </section>;
}

/** Retained context, with excerpts for compact previews and history. */
export function RequestContext({ payload, compact = true }: { payload: RunPayload; compact?: boolean }) {
  const sections = requestContext(payload);
  return sections.length ? <div className="request-context-sections">{sections.map(section => <ContextSection key={section.title + ":" + payload.index} title={section.title} text={section.text} compact={compact} />)}</div>
    : <p className="muted">No separate matched context was recorded. Full instructions are available in the exact API payload.</p>;
}
