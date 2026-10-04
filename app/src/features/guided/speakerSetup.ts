import type { GuidedPreferences } from "../../api/contracts.ts";

/** Adopt investigated settings without replacing edits made while the request was pending. */
export function mergeInvestigationSettings(before: GuidedPreferences, current: GuidedPreferences, saved: GuidedPreferences): GuidedPreferences {
  const engine_options = { ...current.values.engine_options };
  for (const [key, value] of Object.entries(saved.values.engine_options)) {
    if (current.values.engine_options[key] === before.values.engine_options[key]) engine_options[key] = value;
  }
  const widths = JSON.stringify(current.values.widths) === JSON.stringify(before.values.widths) ? saved.values.widths : current.values.widths;
  return { ...current, revision: saved.revision, values: { ...current.values, engine_options, widths } };
}

export function onlyInvestigationSettingsChanged(before: GuidedPreferences, saved: GuidedPreferences, keys: string[]): boolean {
  const rest = (value: GuidedPreferences) => ({ ...value.values, widths: null, engine_options: Object.fromEntries(Object.entries(value.values.engine_options).filter(([key]) => !keys.includes(key))) });
  return JSON.stringify(rest(before)) === JSON.stringify(rest(saved));
}
