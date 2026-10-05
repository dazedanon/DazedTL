import { useEffect, useId, useState } from "react";
import { api } from "../../api/client";
import type { RunPayload } from "../../api/contracts";
import { messageOf } from "../../api/errors";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { ExpandableText } from "../../ui/ExpandableText";
import { RequestText } from "./RequestSource";
import { RequestContext } from "./RequestContext";

const tabs = [{ id: "text", label: "Text" }, { id: "context", label: "Context" }, { id: "payload", label: "API payload" }] as const;

/** Reads the reviewed run only; opening or closing never prepares or submits work. */
export function PreparedRequestPreview({ projectId, runId, estimate, close }: {
  projectId: string; runId: string; estimate: boolean; close: () => void;
}) {
  const tabId = useId();
  const [tab, setTab] = useState<typeof tabs[number]["id"]>("text");
  const [index, setIndex] = useState(0);
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [total, setTotal] = useState(0);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let current = true;
    setPending(true); setError(""); setPayload(null);
    void api.guided.payload(projectId, runId, index).then(value => {
      if (current) { setPayload(value); setTotal(value.total); }
    }).catch(failure => { if (current) setError(messageOf(failure)); })
      .finally(() => { if (current) setPending(false); });
    return () => { current = false; };
  }, [projectId, runId, index, retry]);
  const visible = payload?.index === index ? payload : null;
  return <Modal label="Preview request" className="guided-sheet translation-review prepared-request-preview" onDismiss={close}>
    <header className="guided-sheet-heading"><h2>Preview request</h2>
      <p className="muted">{estimate ? "Local estimate preview. Final requests may reflect resolved speaker names." : "Prepared Batch request, before submission."}</p>
    </header>
    <div className="guided-sheet-body payload-inspector prepared-request-body">
      <div className="prepared-request-toolbar">
        <Tabs id={tabId} label="Preview content" items={tabs} value={tab} onChange={setTab} />
        <div className="prepared-request-navigation">
          <span>{total ? `Request ${index + 1} of ${total}` : "Prepared request"}</span>
          {total > 1 && <div className="actions"><Button variant="quiet" disabled={index === 0} onClick={() => setIndex(value => value - 1)}>Previous</Button>
            <Button variant="quiet" disabled={index >= total - 1} onClick={() => setIndex(value => value + 1)}>Next</Button></div>}
        </div>
      </div>
      {tabs.map(item => <div className="request-reader" key={`${index}:${item.id}`} hidden={tab !== item.id} tabIndex={0} aria-label={`Prepared request: ${item.label}`} aria-busy={pending}>
        <TabPanel id={tabId} value={item.id}>
          {error ? <><Message message={error} /><Button onClick={() => setRetry(value => value + 1)}>Try again</Button></>
            : !visible ? <p className="muted" role="status">Reading prepared request…</p>
            : item.id === "text" ? <RequestText payload={visible} />
            : item.id === "context" ? <RequestContext payload={visible} />
            : <ExpandableText text={JSON.stringify(visible.exact, null, 2) ?? "Not recorded"} label="API payload" />}
        </TabPanel>
      </div>)}
    </div>
    <ActionBar feedback={null}><Button onClick={close}>Back to review</Button></ActionBar>
  </Modal>;
}
