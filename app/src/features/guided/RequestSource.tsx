import type { RunPayload } from "../../api/contracts";
import { requestContext } from "./translationView";

/** The same retained context in file previews and the run inspector. */
export function RequestSource({ payload }: { payload: RunPayload }) {
  const context = requestContext(payload);
  return <div className="request-source-context"><section><h3>Lines to translate</h3>
    {payload.source ? <dl className="translation-source-lines">{Object.entries(payload.source).map(([key, text]) => <div key={key}><dt>{key}</dt><dd>{text}</dd></div>)}</dl> : <p>Source is contained in the exact payload.</p>}
    </section><section><h3>Matched context</h3>
    {context.length ? context.map(section => section.notes ? <details key={section.title}><summary>{section.title}</summary><pre>{section.text}</pre></details>
      : <section key={section.title} className="translation-matched-context"><h4>{section.title}</h4><pre>{section.text}</pre></section>)
      : <p className="muted">No separate matched context was recorded. Full instructions are available in the exact payload.</p>}
    </section></div>;
}
