import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { CircleHelp } from "lucide-react";
import { placeOnOpen, placePopover } from "./popoverPlacement";

/** The right edge of the room a button's page offers: its scrolling
 * container's content, which stops short of that container's scrollbar. */
function roomRight(element: HTMLElement) {
  for (
    let parent = element.parentElement;
    parent;
    parent = parent.parentElement
  ) {
    if (/auto|scroll/.test(getComputedStyle(parent).overflowY)) {
      const box = parent.getBoundingClientRect();
      return Math.min(
        window.innerWidth,
        box.left + parent.clientLeft + parent.clientWidth,
      );
    }
  }
  return window.innerWidth;
}

export function HelpPopover({
  label,
  children,
  id,
}: {
  label: string;
  children: ReactNode;
  id?: string;
}) {
  const generatedId = useId();
  const contentId = id || generatedId;
  const button = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const position = () => {
    if (button.current && popover.current)
      placePopover(popover.current, button.current, {
        gap: 8,
        right: roomRight(button.current),
      });
  };
  // Opening places it; an open note follows its button.
  useEffect(() => {
    if (!open) return;
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [open]);
  return (
    <>
      <button
        ref={button}
        type="button"
        className="help-button"
        popoverTarget={contentId}
        aria-label={`Help: ${label}`}
        aria-expanded={open}
        aria-controls={contentId}
      >
        <CircleHelp size={16} aria-hidden="true" />
      </button>
      <div
        ref={popover}
        id={contentId}
        popover="auto"
        className="help-popover"
        onBeforeToggle={(event) => placeOnOpen(event, position)}
        onToggle={(event) => setOpen(event.newState === "open")}
      >
        {children}
      </div>
    </>
  );
}
