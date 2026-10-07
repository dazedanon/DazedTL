/** How a click or key changes a list's checkmarks, as in a file manager. */
export type SelectionGesture = "toggle" | "replace" | "range" | "add-range";
export type Modifiers = {
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
};

/**
 * Shift extends from the anchor, Ctrl/Cmd or a checkbox toggles one item, and
 * a plain click chooses only its item.
 */
export const selectionGesture = (
  event: Modifiers,
  checkbox = false,
): SelectionGesture =>
  event.shiftKey
    ? event.ctrlKey || event.metaKey
      ? "add-range"
      : "range"
    : checkbox || event.ctrlKey || event.metaKey
      ? "toggle"
      : "replace";

/**
 * Checkmarks are the scope. Focus is never a second, highlight-only selection.
 * `visible` needs the items from the anchor to the target in order; a range
 * whose anchor is not among them chooses the target alone.
 */
export function selectItem(
  selected: readonly string[],
  visible: readonly string[],
  target: string,
  gesture: SelectionGesture,
  anchor: string | null,
) {
  const end = visible.indexOf(target);
  if (end < 0) return { selected: [...selected], anchor };
  const start = anchor === null ? -1 : visible.indexOf(anchor);
  const range = gesture === "range" || gesture === "add-range";
  const names =
    range && start >= 0
      ? visible.slice(Math.min(start, end), Math.max(start, end) + 1)
      : [target];
  const result = new Set(
    gesture === "replace" || gesture === "range" ? [] : selected,
  );
  if (gesture === "toggle" && result.has(target)) result.delete(target);
  else for (const name of names) result.add(name);
  return {
    selected: [...result],
    anchor: range && start >= 0 ? anchor : target,
  };
}

/**
 * Moves focus to a list item for a key or a click. Browsers decide whether
 * focus moved by a script draws its ring from earlier input, so the ring
 * follows the gesture instead: keys always draw it and clicks never do.
 */
export function focusItem(element: HTMLElement, by: "key" | "pointer") {
  element.focus({ preventScroll: true });
  element.dataset.focusBy = by;
  element.addEventListener("blur", () => delete element.dataset.focusBy, {
    once: true,
  });
}
