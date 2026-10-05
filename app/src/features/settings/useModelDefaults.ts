import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type { ModelDefaults } from "../../api/contracts";

export function useModelDefaults(
  connectionId: string,
  model: string,
  checkedAt?: string | null,
  host = "",
) {
  const [attempt, retry] = useState(0);
  const [result, setResult] = useState<{
    key: string;
    value?: ModelDefaults;
    error?: string;
  }>();
  const key = JSON.stringify([connectionId, model, checkedAt, host, attempt]);
  useEffect(() => {
    if (!model) return;
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
  }, [key, connectionId, model]);
  return {
    value: result?.key === key ? result.value : undefined,
    error: result?.key === key ? result.error : undefined,
    loading: !!model && result?.key !== key,
    retry: () => retry((value) => value + 1),
  };
}
