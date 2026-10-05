import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { useAction } from "../../state/useAction";
import { Button } from "../../ui/Button";
import { ComboBox } from "../../ui/ComboBox";
import { FieldRow } from "../../ui/FieldRow";

type Host = { slug: string; name: string };
// Public, model-scoped suggestions survive editor and tab revisits. Refresh is
// explicit; cached metadata never grants execution or account eligibility.
const hostLists = new Map<string, Host[]>();

export function OpenRouterHost({
  model,
  value,
  onChange,
  disabled,
  checksEnabled,
}: {
  model: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  checksEnabled: boolean;
}) {
  const action = useAction();
  const [hosts, setHosts] = useState<Host[] | null>(
    () => hostLists.get(model) ?? null,
  );
  const mounted = useRef(false);
  const load = useCallback(
    (notice = "") =>
      action.run(async () => {
        const hosts = await api.openrouterHosts(model);
        hostLists.delete(model);
        hostLists.set(model, hosts);
        if (hostLists.size > 32)
          hostLists.delete(hostLists.keys().next().value!);
        if (mounted.current) setHosts(hosts);
      }, notice),
    [model, action.run],
  );
  useEffect(() => {
    mounted.current = true;
    if (model && checksEnabled && !hostLists.has(model)) void load();
    return () => {
      mounted.current = false;
    };
  }, [model, checksEnabled, load]);
  const selected = hosts?.find((host) => host.slug === value);
  return (
    <FieldRow
      id="connection-host"
      label="Host"
      help={
        model
          ? `Hosts for ${model}. A selected host is exclusive for new runs.`
          : "Choose a model in Preferences to see its supported hosts."
      }
      error={action.error}
    >
      {(control) => (
        <>
          <ComboBox
            {...control}
            readOnly
            value={value}
            onChange={onChange}
            disabled={disabled || !model}
            title={selected?.name || value || "Automatic"}
            options={[
              { value: "", label: "Automatic" },
              ...(hosts || []).map((host) => ({
                value: host.slug,
                label: host.name,
              })),
            ]}
          />
          {model && (
            <div className="actions connection-host-actions">
              <Button
                variant="quiet"
                pending={action.busy}
                disabled={disabled || !checksEnabled}
                onClick={() => load("Hosts updated.")}
              >
                {action.busy
                  ? "Loading hosts…"
                  : action.error
                    ? "Retry host lookup"
                    : "Refresh hosts"}
              </Button>
              {action.notice && <small role="status">{action.notice}</small>}
              {!checksEnabled && (
                <small>Host lookup is unavailable in offline mode.</small>
              )}
            </div>
          )}
          {hosts &&
            !action.error &&
            !action.busy &&
            (value && !selected ? (
              <small role="status">
                The saved host is not listed for this model. Choose another host
                or Automatic.
              </small>
            ) : (
              hosts.length === 0 && (
                <small role="status">
                  No hosts are currently listed for this model.
                </small>
              )
            ))}
        </>
      )}
    </FieldRow>
  );
}
