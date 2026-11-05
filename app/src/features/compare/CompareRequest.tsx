import { useId, useState } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type { CompareModel, Job, RunPayload } from "../../api/contracts";
import { useRead } from "../../state/useRead";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { TabPanel, Tabs } from "../../ui/Tabs";
import { RequestFailure } from "../guided/RequestFailure";
import { RequestPager } from "../guided/RequestPager";
import { RequestSource } from "../guided/RequestSource";
import { RequestTechnical } from "../guided/RequestTechnical";
import { responseText } from "../guided/requestView";
import { keptRequests } from "./compareView";

const tabs = [
  { id: "source", label: "Source" },
  { id: "response", label: "Response" },
  { id: "technical", label: "Technical" },
] as const;

/**
 * Show request: the requests a compared model's translation sent, as a
 * run's inspector shows them, one at a time. It only reads them.
 */
export function CompareRequest({
  projectId,
  translationId,
  model,
  close,
}: {
  projectId: string;
  translationId: string;
  model: CompareModel;
  close: () => void;
}) {
  const tabId = useId();
  const [tab, setTab] = useState<(typeof tabs)[number]["id"]>("source");
  const [index, setIndex] = useState(0);
  const { kept: total, note } = keptRequests(model);
  const request = useRead(`${translationId}:${model.index}:${index}`, () =>
    api.compare.request(projectId, translationId, model.index, index),
  );
  const payload: RunPayload | undefined = request.value;
  const error = request.error === undefined ? "" : messageOf(request.error);
  // The request viewers read a run's model and state from its job.
  const job = {
    id: translationId,
    status: "complete",
    message: "",
    log: [],
    model: model.model,
  } satisfies Job;
  return (
    <Modal
      label="Show request"
      size="lg"
      className="guided-sheet prepared-request-preview compare-request"
      onDismiss={close}
    >
      <DialogHeader
        title="Show request"
        description={[`${model.model} on ${model.connection}`, note]
          .filter(Boolean)
          .join(". ")}
        onClose={close}
      />
      <DialogBody className="payload-inspector prepared-request-body">
        <div className="request-toolbar">
          <Tabs
            id={tabId}
            label="Request content"
            items={tabs}
            value={tab}
            onChange={setTab}
          />
          <RequestPager index={index} total={total} change={setIndex} />
        </div>
        <div
          className="request-reader"
          tabIndex={0}
          aria-label={`Request: ${tabs.find((item) => item.id === tab)?.label}`}
          aria-busy={request.pending}
        >
          <TabPanel id={tabId} value={tab}>
            {error ? (
              <>
                <Message message={error} />
                <Button onClick={request.retry}>Try again</Button>
              </>
            ) : !payload ? (
              <p className="muted" role="status">
                Reading the request…
              </p>
            ) : tab === "source" ? (
              <RequestSource payload={payload} />
            ) : tab === "response" ? (
              <>
                <RequestFailure payload={payload} details />
                {payload.response != null ? (
                  <pre>{responseText(payload.response)}</pre>
                ) : (
                  <p className="muted">No response was kept.</p>
                )}
              </>
            ) : (
              <RequestTechnical
                payload={payload}
                job={job}
                compact={false}
                showEstimate={false}
              />
            )}
          </TabPanel>
        </div>
      </DialogBody>
    </Modal>
  );
}
