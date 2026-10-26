/**
 * Where a popover that opens from a button, such as a menu or a help note,
 * sits, and when it gets there.
 *
 * A button opens its popover (`popoverTarget`) in the click's own task, but
 * the popover's toggle event can arrive only after the next frame has painted
 * it at the window's corner, as it did under load. That frame runs its
 * animation callbacks before it paints, so a popover placed in one never
 * shows unplaced. ComboBox, which opens its list itself, places it right
 * after showing it instead.
 */
export function placeOnOpen(event: { newState: string }, place: () => void) {
  if (event.newState === "open") requestAnimationFrame(place);
}

/**
 * Places `popup` below `anchor`, or above it when it does not fit below and
 * there is more room above, kept a margin inside the window and left of
 * `right`. With `fit`, its height is capped to the room on the side it took.
 */
export function placePopover(
  popup: HTMLElement,
  anchor: HTMLElement,
  {
    align = "start",
    gap = 4,
    right = window.innerWidth,
    fit = false,
  }: {
    /** Which of the anchor's edges the popover lines up with. */
    align?: "start" | "end";
    gap?: number;
    /** The right edge of the room the popover may take. */
    right?: number;
    fit?: boolean;
  } = {},
) {
  const margin = 8;
  if (fit) popup.style.maxHeight = "";
  const rect = anchor.getBoundingClientRect();
  const box = popup.getBoundingClientRect();
  const below = window.innerHeight - rect.bottom - gap - margin;
  const above = rect.top - gap - margin;
  const upwards = box.height > below && above > below;
  const left = align === "end" ? rect.right - box.width : rect.left;
  popup.style.left = `${Math.max(margin, Math.min(left, right - box.width - margin))}px`;
  popup.style.top = `${Math.max(margin, upwards ? rect.top - gap - box.height : rect.bottom + gap)}px`;
  if (fit) popup.style.maxHeight = `${upwards ? above : below}px`;
}
