import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type { ModelDefaults } from "../../api/contracts";
import { useTabPanelShown } from "../../ui/Tabs";

/**
 * The active connection's defaults for `model`, read again whenever `basis`,
 * what they depend on beside the model (such as the connection's last check
 * and address), changes.
 */
export function useModelDefaults(
  connectionId: string,
  model: string,
  basis: string,
  host = "",
) {
  const [attempt, retry] = useState(0);
  const [result, setResult] = useState<{
    key: string;
    value?: ModelDefaults;
    error?: string;
  }>();
  const key = JSON.stringify([connectionId, model, basis, host, attempt]);
  const current = result?.key === key;
  // A hidden Settings tab reads them again once it shows.
  const shown = useTabPanelShown();
  useEffect(() => {
    if (!model || current || !shown) return;
    let active = true;
    // Typing a model ID should not launch a resolver for each keystroke.
    const timer = setTimeout(() => {
      api.modelDefaults(connectionId, model).then(
        (value) => {
          if (active) setResult({ key, value });
        },
        (error) => {
          if (active) setResult({ key, error: messageOf(error) });
        },
      );
    }, 400);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [key, connectionId, model, current, shown]);
  return {
    value: current ? result.value : undefined,
    error: current ? result.error : undefined,
    loading: !!model && !current,
    retry: () => retry((value) => value + 1),
  };
}
