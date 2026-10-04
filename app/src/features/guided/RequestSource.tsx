import type { RunPayload } from "../../api/contracts";
import { RequestContext } from "./RequestContext";

/** The same retained context in file previews and the run inspector. */
export function RequestSource({ payload }: { payload: RunPayload }) {
  return <div className="request-source-context"><section><h3>Lines to translate</h3>
    {payload.source ? <dl className="translation-source-lines">{Object.entries(payload.source).map(([key, text]) => <div key={key}><dt>{key}</dt><dd>{text}</dd></div>)}</dl> : <p>Source is contained in the exact payload.</p>}
    </section><section><h3>Matched context</h3>
    <RequestContext payload={payload} />
    </section></div>;
}
