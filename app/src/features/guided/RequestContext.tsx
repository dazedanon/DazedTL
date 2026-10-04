import type { RunPayload } from "../../api/contracts";
import { ExpandableText } from "../../ui/ExpandableText";
import { requestContext } from "./translationView";

function ContextSection({ title, text }: { title: string; text: string }) {
  return <section className="translation-matched-context">
    <h3>{title}</h3>
    <ExpandableText text={text} label={title} />
  </section>;
}

/** Compact retained context, shared by file previews and request history. */
export function RequestContext({ payload }: { payload: RunPayload }) {
  const sections = requestContext(payload);
  return sections.length ? sections.map(section => <ContextSection key={section.title + ":" + payload.index} title={section.title} text={section.text} />)
    : <p className="muted">No separate matched context was recorded. Full instructions are available in the exact API payload.</p>;
}
