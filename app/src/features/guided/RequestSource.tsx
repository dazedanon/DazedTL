import type { RunPayload } from "../../api/contracts";
import { RequestContext } from "./RequestContext";

/** Request text as sent; each placeholder that stood in for a control code is
    marked so its position can be checked. */
export function ProtectedText({ text }: { text: string }) {
  return text.split(/(__PROTECTED_\d+__)/).map((part, index) =>
    index % 2 ? (
      <span
        key={index}
        className="protected-code"
        title="Sent in place of a control code, which is restored after translating"
      >
        {part}
      </span>
    ) : (
      part
    ),
  );
}

export function RequestText({ payload }: { payload: RunPayload }) {
  return (
    <section>
      <h3>Lines to translate</h3>
      {payload.source ? (
        <dl className="translation-source-lines">
          {Object.entries(payload.source).map(([key, text]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>
                <ProtectedText text={text} />
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>Source is contained in the exact payload.</p>
      )}
    </section>
  );
}

/** The same retained text and context in file previews and the run inspector. */
export function RequestSource({ payload }: { payload: RunPayload }) {
  return (
    <div className="request-source-context">
      <RequestText payload={payload} />
      <RequestContext payload={payload} />
    </div>
  );
}
