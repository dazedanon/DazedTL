import { useEffect, useEffectEvent, type RefObject } from "react";

const mac = /Mac|iPhone|iPad/.test(navigator.platform);
/** How a shortcut is written on this platform, for titles and hints. */
export const shortcutLabel = {
  save: mac ? "⌘S" : "Ctrl+S",
  back: mac ? "⌥←" : "Alt+←",
  next: mac ? "⌥→" : "Alt+→",
};
/** The same shortcuts in `aria-keyshortcuts` form. */
export const shortcutKeys = {
  save: mac ? "Meta+S" : "Control+S",
  back: "Alt+ArrowLeft",
  next: "Alt+ArrowRight",
};
export const saveKey = (event: KeyboardEvent) =>
  (mac ? event.metaKey : event.ctrlKey) &&
  !event.altKey &&
  !event.shiftKey &&
  event.key.toLowerCase() === "s";
export const taskKey = (direction: "back" | "next") => (event: KeyboardEvent) =>
  event.altKey &&
  !event.ctrlKey &&
  !event.metaKey &&
  !event.shiftKey &&
  event.key === (direction === "back" ? "ArrowLeft" : "ArrowRight");

const editable = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/**
 * Runs `action` for a key combination while `scope` is on screen and no
 * dialog above it is open. Text fields keep their own keys unless `inFields`.
 * Shortcuts only save or navigate; nothing that spends or publishes gets one.
 */
export function useShortcut(
  matches: (event: KeyboardEvent) => boolean,
  action: (() => void) | null | undefined,
  scope: RefObject<HTMLElement | null>,
  { inFields = false }: { inFields?: boolean } = {},
) {
  const handle = useEffectEvent((event: KeyboardEvent) => {
    const root = scope.current;
    if (!action || !root || event.defaultPrevented || !matches(event)) return;
    if (!root.getClientRects().length) return;
    const dialog = [...document.querySelectorAll("dialog[open]")].at(-1);
    if (dialog && !dialog.contains(root)) return;
    if (!inFields && editable(event.target)) return;
    event.preventDefault();
    if (!event.repeat) action();
  });
  useEffect(() => {
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, []);
}

/** The save shortcut submits a visible editor form while its submit button is enabled. */
export function useSaveForm(form: RefObject<HTMLFormElement | null>) {
  useShortcut(
    saveKey,
    () => {
      const submit = form.current?.querySelector<HTMLButtonElement>(
        "button[type=submit]",
      );
      if (submit && !submit.disabled) form.current!.requestSubmit(submit);
    },
    form,
    { inFields: true },
  );
}
