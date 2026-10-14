import { useLayoutEffect, useRef } from "react";

/**
 * Keeps keyboard work going in a list whose items can remove their own row:
 * once the item an action started from leaves the page, focus moves to the
 * item that takes its place, or the last one. Call the returned function with
 * that item when the action starts.
 */
export function useRefocus(items: () => HTMLElement[]) {
  const armed = useRef<{ node: HTMLElement; index: number } | null>(null);
  useLayoutEffect(() => {
    const target = armed.current;
    if (!target || target.node.isConnected) return;
    armed.current = null;
    // Focus that moved elsewhere in the meantime stays there.
    if (document.activeElement !== document.body) return;
    const all = items();
    all[Math.min(target.index, all.length - 1)]?.focus({ preventScroll: true });
  });
  return (node: HTMLElement | null) => {
    const index = node ? items().indexOf(node) : -1;
    armed.current = node && index >= 0 ? { node, index } : null;
  };
}
