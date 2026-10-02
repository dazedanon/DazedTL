import type { GuidedPreferences } from "../../api/contracts.ts";

/** Adopt investigated flags without replacing edits made while the request was pending. */
export function mergeSpeakerFindings(before: GuidedPreferences, current: GuidedPreferences, saved: GuidedPreferences): GuidedPreferences {
  const engine_options = { ...current.values.engine_options };
  for (const [key, value] of Object.entries(saved.values.engine_options)) {
    if (current.values.engine_options[key] === before.values.engine_options[key]) engine_options[key] = value;
  }
  return { ...current, revision: saved.revision, values: { ...current.values, engine_options } };
}

export function onlySpeakerSettingsChanged(before: GuidedPreferences, saved: GuidedPreferences, keys: string[]): boolean {
  const rest = (value: GuidedPreferences) => ({ ...value.values, engine_options: Object.fromEntries(Object.entries(value.values.engine_options).filter(([key]) => !keys.includes(key))) });
  return JSON.stringify(rest(before)) === JSON.stringify(rest(saved));
}
