import { useLayoutEffect, useRef, useState } from "react";

let canvas: HTMLCanvasElement | undefined;
const graphemes = new Intl.Segmenter(undefined, { granularity: "grapheme" });

/**
 * The end of the text `element` lays out in its first child that fits the
 * element after an ellipsis, or undefined when the whole text fits. Widths
 * come from the laid-out text itself, so fonts, fallback glyphs and spacing
 * count as the page draws them.
 */
function fittedEnd(element: HTMLElement) {
  if (element.scrollWidth <= element.clientWidth) return undefined;
  const node = element.firstElementChild?.firstChild;
  if (!(node instanceof Text) || !node.data) return undefined;
  const text = node.data;
  const style = getComputedStyle(element);
  const width =
    element.clientWidth -
    parseFloat(style.paddingLeft) -
    parseFloat(style.paddingRight);
  canvas ??= document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return undefined;
  context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
  const room = width - context.measureText("…").width;
  // Cut only between whole characters, never inside one built from several
  // code points.
  const cuts = Array.from(graphemes.segment(text), (part) => part.index);
  const range = document.createRange();
  range.setEnd(node, text.length);
  const fits = (index: number) => {
    range.setStart(node, cuts[index]);
    return range.getBoundingClientRect().width <= room;
  };
  let low = 1;
  let high = cuts.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (fits(middle)) high = middle;
    else low = middle + 1;
  }
  return `…${text.slice(cuts[low] ?? text.length)}`;
}

/**
 * Shortens the text of the element the returned ref names at its start, as
 * `.path-text` and `.file-name` show it. CSS's own ellipsis in a
 * right-to-left box drops whole characters from a line laid out against its
 * right edge, so the ellipsis lands up to a character's width inside the left
 * edge and the text no longer lines up with the lines above it; measuring
 * puts the ellipsis on the edge. The element keeps the whole text in its
 * first child, for its width, copying and assistive technology, and shows
 * `shown` over it.
 */
export function useStartEllipsis<T extends HTMLElement>(
  text: string,
  active = true,
) {
  const ref = useRef<T>(null);
  const [shown, setShown] = useState<string>();
  useLayoutEffect(() => {
    const element = ref.current;
    if (!active || !element) {
      setShown(undefined);
      return;
    }
    const fit = () => setShown(fittedEnd(element));
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    // A font that finishes loading changes every width.
    document.fonts.addEventListener("loadingdone", fit);
    return () => {
      observer.disconnect();
      document.fonts.removeEventListener("loadingdone", fit);
    };
  }, [text, active]);
  return { ref, shown };
}
