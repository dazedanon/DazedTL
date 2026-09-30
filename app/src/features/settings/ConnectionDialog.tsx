import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Modal } from "../../ui/Modal";
import { registerLeaveGuard } from "../../state/leaveGuards";
import { useAction } from "../../state/useAction";
import { Button } from "../../ui/Button";
import type { Settings } from "../../api/contracts";

export interface ConnectionInput {
  name: string;
  secret: string;
  endpoint: string;
  keyless: boolean;
}
type SavedConnection = Settings["keys"][number];

export default function ConnectionDialog({
  connection,
  names,
  save,
  close,
}: {
  connection: SavedConnection | null;
  names: string[];
  save: (value: ConnectionInput) => Promise<void>;
  close: () => void;
}) {
  const initial = {
    name: connection?.name || "",
    secret: "",
    endpoint: connection?.endpoint || "",
    keyless: connection?.keyless || false,
  };
  const [value, setValue] = useState<ConnectionInput>(initial);
  const action = useAction();
  const { busy, error } = action;
  const dirty = useRef(false);
  dirty.current = JSON.stringify(value) !== JSON.stringify(initial);
  useEffect(
    () =>
      registerLeaveGuard(async () => {
        if (dirty.current)
          throw new Error(
            "Save or cancel the connection editor before leaving.",
          );
      }),
    [],
  );
  const needsKey = !value.keyless && !connection?.has_secret;
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!connection && names.includes(value.name.trim())) {
      action.report(
        "That connection already exists. Choose a different name or use Edit.",
      );
      return;
    }
    await action.run(async () => {
      await save(value);
      dirty.current = false;
      close();
    });
  }

  return (
    <Modal
      label={connection ? "Edit connection" : "Add connection"}
      className="connection-editor"
      onDismiss={close}
      dismissible={!busy}
    >
      <header className="connection-editor-heading">
        <h2>{connection ? "Edit connection" : "Add connection"}</h2>
        <Button
          type="button"
          variant="quiet"
          disabled={busy}
          aria-label="Close connection editor"
          onClick={close}
        >
          <X size={17} />
        </Button>
      </header>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <label htmlFor="connection-name">
            Connection name
            <input
              id="connection-name"
              value={value.name}
              required
              maxLength={100}
              readOnly={!!connection}
              placeholder="My provider"
              autoFocus={!connection}
              onChange={(event) =>
                setValue({ ...value, name: event.target.value })
              }
            />
          </label>
          <label htmlFor="connection-key">
            API key
            <input
              id="connection-key"
              type="password"
              autoComplete="off"
              value={value.secret}
              required={needsKey}
              disabled={value.keyless}
              placeholder={
                connection?.has_secret
                  ? "Leave blank to keep the saved key"
                  : ""
              }
              autoFocus={!!connection}
              onChange={(event) =>
                setValue({ ...value, secret: event.target.value })
              }
            />
          </label>
          <label htmlFor="connection-endpoint">
            Endpoint
            <input
              id="connection-endpoint"
              type="url"
              value={value.endpoint}
              required={value.keyless}
              placeholder="Leave blank for the provider default"
              onChange={(event) =>
                setValue({ ...value, endpoint: event.target.value })
              }
            />
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={value.keyless}
              onChange={(event) =>
                setValue({ ...value, keyless: event.target.checked })
              }
            />
            This endpoint does not require an API key
          </label>
        </fieldset>
        {error && (
          <p className="banner" role="alert">
            {error}
          </p>
        )}
        <footer className="connection-editor-footer">
          <Button type="button" disabled={busy} onClick={close}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={busy || !value.name.trim()}
          >
            {busy ? "Saving…" : "Save connection"}
          </Button>
        </footer>
      </form>
    </Modal>
  );
}
