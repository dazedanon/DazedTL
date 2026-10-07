/** A run's failure banner on its task, which the user can dismiss. */
import { useState } from "react";
import { Message } from "../../ui/Feedback";

const storageKey = (run: string) => "dazedtl:dismissed-failure:" + run;

/** Remembers a reason without storing it; a reason can quote game text. */
function fingerprint(text: string) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index++)
    hash = Math.imul(hash ^ text.charCodeAt(index), 0x01000193);
  return (hash >>> 0).toString(36);
}

function stored(run: string) {
  try {
    return localStorage.getItem(storageKey(run));
  } catch {
    return null;
  }
}

/** Dismissing hides only this banner, never the run, its history or its
 * execution guards. The run's next, different reason shows again. */
export function RunFailure({
  run,
  reason,
  message,
}: {
  run: string;
  reason: string;
  message: string;
}) {
  const identity = fingerprint(reason);
  const [dismissed, setDismissed] = useState("");
  if (dismissed === run + ":" + identity || stored(run) === identity)
    return null;
  return (
    <Message
      message={message}
      onDismiss={() => {
        try {
          localStorage.setItem(storageKey(run), identity);
        } catch {
          // The banner stays hidden until the next launch.
        }
        setDismissed(run + ":" + identity);
      }}
    />
  );
}
