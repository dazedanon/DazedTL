import { useState } from "react";
import { api } from "../../api/client";
import type { Connection } from "../../api/contracts";
import { messageOf } from "../../api/errors";
import { useAction } from "../../state/useAction";
import { useRead } from "../../state/useRead";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Message } from "../../ui/Feedback";
import { CheckField } from "../../ui/FieldRow";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";

/**
 * Confirms removing a connection: what is forgotten, which connection takes
 * over, and the unfinished runs that can no longer use it.
 */
export function RemoveConnection({
  connection,
  next,
  remove,
  close,
}: {
  connection: Connection;
  /** The connection that becomes active when this active one is removed. */
  next?: Connection;
  remove: (unfinished: number) => Promise<unknown>;
  close: () => void;
}) {
  const usage = useRead(connection.id, () =>
    api.connectionUsage(connection.id),
  );
  const action = useAction();
  const [accepted, setAccepted] = useState(false);
  const unfinished = usage.value?.unfinished ?? 0;
  return (
    <Modal
      label="Remove connection"
      size="sm"
      dismissible={!action.busy}
      onDismiss={close}
    >
      <DialogHeader title={`Remove ${connection.name}?`} />
      <DialogBody>
        <p>
          {connection.has_secret
            ? "Its saved API key and model choices are removed from DazedTL."
            : "Its server and model choices are removed from DazedTL."}{" "}
          {next
            ? `${next.name} becomes the active connection.`
            : "Add a connection before translating with an API."}
        </p>
        {usage.pending && (
          <p className="muted" role="status">
            Checking saved runs…
          </p>
        )}
        {!!usage.error && (
          <Message
            message={`Could not check saved runs. ${messageOf(usage.error)}`}
          />
        )}
        {unfinished > 0 && (
          <>
            <Notice tone="warning">
              {unfinished === 1
                ? "1 unfinished saved run uses this connection. After removal it can’t be resumed, and its Batches can’t be checked or collected."
                : `${unfinished} unfinished saved runs use this connection. After removal they can’t be resumed, and their Batches can’t be checked or collected.`}{" "}
              Uncollected paid results are lost.
            </Notice>
            <CheckField
              id="remove-connection-accept"
              label="Remove it anyway"
              checked={accepted}
              disabled={action.busy}
              onChange={setAccepted}
            />
          </>
        )}
      </DialogBody>
      <ActionBar feedback={<Message message={action.error} />}>
        <Button data-autofocus disabled={action.busy} onClick={close}>
          Cancel
        </Button>
        <Button
          variant="danger"
          pending={action.busy}
          disabled={!usage.value || (unfinished > 0 && !accepted)}
          onClick={() =>
            action.run(async () => {
              await remove(unfinished);
              close();
            })
          }
        >
          Remove connection
        </Button>
      </ActionBar>
    </Modal>
  );
}
