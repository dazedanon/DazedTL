import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import type {
  Connection,
  ConnectionInput,
  Provider,
  Settings,
} from "../../api/contracts";
import { registerLeaveGuard } from "../../state/leaveGuards";
import { useAction } from "../../state/useAction";
import { PageBody } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { FieldRow } from "../../ui/FieldRow";
import { Button } from "../../ui/Button";
import { ActionBar } from "../../ui/ActionBar";
import { OpenRouterHost } from "./OpenRouterHost";

export default function ConnectionEditor({
  connection,
  providers,
  running,
  checksEnabled,
  save,
  cancel,
}: {
  connection?: Connection;
  providers: Settings["providers"];
  running: boolean;
  checksEnabled: boolean;
  save: (input: ConnectionInput) => Promise<unknown>;
  cancel: () => void;
}) {
  const initial = {
    provider: connection ? connection.provider || "" : "openai",
    protocol: connection?.protocol || "openai",
    name: connection?.name || "",
    secret: "",
    endpoint: connection?.endpoint || "",
    keyless: connection?.keyless || false,
    organization: connection?.organization || "",
    openrouter_host: connection?.openrouter_host || "",
    reuse_secret: false,
  };
  const [value, setValue] = useState(initial);
  const [revealed, setRevealed] = useState(false);
  const action = useAction();
  const dirty = useRef(false);
  const pending = useRef<Promise<unknown> | null>(null);
  dirty.current = JSON.stringify(value) !== JSON.stringify(initial);
  useEffect(
    () =>
      registerLeaveGuard(async () => {
        if (pending.current) await pending.current;
        if (dirty.current)
          throw new Error(
            "Save or cancel the connection changes before leaving.",
          );
      }),
    [],
  );
  const custom = value.provider === "custom";
  const hostModel =
    connection?.provider === "openrouter" ? connection.model : "";
  const definition = providers.find((item) => item.id === value.provider);
  const sameRoute =
    connection?.provider === value.provider &&
    connection?.protocol === value.protocol &&
    connection.endpoint.replace(/\/$/, "") ===
      value.endpoint.trim().replace(/\/$/, "");
  const keepKey = !!(
    connection?.has_secret &&
    (sameRoute || value.reuse_secret)
  );
  function chooseProvider(provider: string) {
    setRevealed(false);
    setValue((current) => ({
      ...current,
      provider,
      protocol:
        providers.find((item) => item.id === provider)?.protocol || "openai",
      endpoint:
        provider === "custom" && connection?.needsSetup
          ? connection.endpoint
          : "",
      secret: "",
      reuse_secret: false,
      keyless: false,
      organization: "",
      openrouter_host: "",
    }));
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!value.provider) return;
    const task = action.run(async () => {
      await save({
        ...value,
        provider: value.provider as Provider,
        connection_id: connection?.id,
      });
      dirty.current = false;
      setValue((current) => ({ ...current, secret: "" }));
      cancel();
    });
    pending.current = task;
    await task;
    pending.current = null;
  }
  function discard() {
    dirty.current = false;
    setValue(initial);
    action.clear();
    setRevealed(false);
    cancel();
  }
  const disabled = action.busy || running;
  return (
    <form className="editor-form" onSubmit={submit} autoComplete="off">
      <PageBody>
        <Section title={connection ? "Edit connection" : "Connect your API"}>
          <p className="settings-intro">
            {connection?.needsSetup
              ? "Choose the provider, then confirm the saved key or enter a replacement."
              : "Choose a provider and add your API key."}
          </p>
          <fieldset disabled={disabled}>
            <FieldRow id="connection-provider" label="Provider">
              {(control) => (
                <select
                  {...control}
                  required
                  value={value.provider}
                  onChange={(event) => chooseProvider(event.target.value)}
                >
                  <option value="" disabled>
                    Choose provider
                  </option>
                  {providers.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.label}
                    </option>
                  ))}
                </select>
              )}
            </FieldRow>
            {value.provider === "openrouter" && (
              <OpenRouterHost
                key={hostModel}
                model={hostModel}
                value={value.openrouter_host}
                disabled={disabled}
                checksEnabled={checksEnabled}
                onChange={(openrouter_host) =>
                  setValue((current) => ({ ...current, openrouter_host }))
                }
              />
            )}
            {!value.keyless && (
              <FieldRow
                id="connection-secret"
                label="API key"
                help={
                  keepKey
                    ? "Leave blank to keep the saved key."
                    : "Use the API key from your provider account."
                }
              >
                {(control) => (
                  <div className="connection-secret">
                    <input
                      {...control}
                      type={revealed ? "text" : "password"}
                      value={value.secret}
                      required={!keepKey}
                      disabled={value.reuse_secret}
                      maxLength={16000}
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={keepKey ? "Saved key" : "Paste API key"}
                      onChange={(event) =>
                        setValue({ ...value, secret: event.target.value })
                      }
                    />
                    <Button
                      variant="quiet"
                      disabled={value.reuse_secret}
                      aria-label={
                        revealed
                          ? "Hide entered API key"
                          : "Show entered API key"
                      }
                      onClick={() => setRevealed(!revealed)}
                    >
                      {revealed ? <EyeOff size={16} /> : <Eye size={16} />}
                    </Button>
                  </div>
                )}
              </FieldRow>
            )}
            {connection?.has_secret &&
              value.provider &&
              !sameRoute &&
              !value.keyless && (
                <label className="connection-keyless">
                  <input
                    type="checkbox"
                    checked={value.reuse_secret}
                    onChange={(event) =>
                      setValue({
                        ...value,
                        reuse_secret: event.target.checked,
                        secret: "",
                      })
                    }
                  />
                  Use the saved key with this provider or server
                </label>
              )}
            {custom && (
              <>
                <FieldRow
                  id="connection-endpoint"
                  label="Server URL"
                  help="Use the API base URL, including /v1 when your server requires it."
                >
                  {(control) => (
                    <input
                      {...control}
                      type="url"
                      required
                      value={value.endpoint}
                      placeholder="http://localhost:8000/v1"
                      onChange={(event) =>
                        setValue({
                          ...value,
                          endpoint: event.target.value,
                          reuse_secret: false,
                        })
                      }
                    />
                  )}
                </FieldRow>
                <label className="connection-keyless">
                  <input
                    type="checkbox"
                    checked={value.keyless}
                    onChange={(event) =>
                      setValue({
                        ...value,
                        keyless: event.target.checked,
                        secret: "",
                        reuse_secret: false,
                      })
                    }
                  />
                  This server does not require an API key
                </label>
              </>
            )}
            <details className="settings-advanced">
              <summary>Advanced connection settings</summary>
              <FieldRow
                id="connection-name"
                label="Connection name"
                help="Leave blank for an automatic name."
              >
                {(control) => (
                  <input
                    {...control}
                    value={value.name}
                    maxLength={100}
                    placeholder={definition?.label || "Automatic"}
                    onChange={(event) =>
                      setValue({ ...value, name: event.target.value })
                    }
                  />
                )}
              </FieldRow>
              {custom && (
                <FieldRow
                  id="connection-protocol"
                  label="Protocol"
                  help="Use the protocol supported by your server."
                >
                  {(control) => (
                    <select
                      {...control}
                      value={value.protocol}
                      onChange={(event) =>
                        setValue({
                          ...value,
                          protocol: event.target
                            .value as ConnectionInput["protocol"],
                          secret: "",
                          reuse_secret: false,
                        })
                      }
                    >
                      <option value="openai">OpenAI-compatible</option>
                      <option value="gemini">Gemini-compatible</option>
                      <option value="mistral">Mistral-compatible</option>
                    </select>
                  )}
                </FieldRow>
              )}
              {value.protocol === "openai" &&
                value.provider !== "openrouter" && (
                  <FieldRow
                    id="connection-organization"
                    label="Organization ID"
                    help="Optional for OpenAI organization-specific access."
                  >
                    {(control) => (
                      <input
                        {...control}
                        value={value.organization}
                        maxLength={200}
                        placeholder="Provider default"
                        onChange={(event) =>
                          setValue({
                            ...value,
                            organization: event.target.value,
                          })
                        }
                      />
                    )}
                  </FieldRow>
                )}
            </details>
          </fieldset>
        </Section>
      </PageBody>
      <ActionBar
        feedback={
          <div
            className={`feedback ${action.error ? "error" : ""}`}
            role={action.error ? "alert" : "status"}
          >
            {action.error ||
              (running
                ? "Connections can be changed after the current run finishes."
                : action.busy
                  ? "Saving connection…"
                  : dirty.current
                    ? "Unsaved connection changes"
                    : "The key is stored only when you save this connection.")}
          </div>
        }
      >
        <Button disabled={action.busy} onClick={discard}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          pending={action.busy}
          disabled={running || !dirty.current || !value.provider}
        >
          Save connection
        </Button>
      </ActionBar>
    </form>
  );
}
