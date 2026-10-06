/**
 * Settings saved outside the Settings page (such as the model menu) announce
 * themselves, so a clean Settings page reloads instead of showing old values.
 */
const listeners = new Set<() => void>();

export function onSettingsSaved(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function settingsSaved() {
  for (const listener of listeners) listener();
}
