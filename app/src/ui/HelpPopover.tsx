import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { CircleHelp } from "lucide-react";

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
    if (!button.current || !popover.current) return;
    const anchor = button.current.getBoundingClientRect();
    const box = popover.current.getBoundingClientRect();
    const gap = 8;
    popover.current.style.left = `${Math.max(gap, Math.min(anchor.left, window.innerWidth - box.width - gap))}px`;
    popover.current.style.top = `${Math.max(
      gap,
      anchor.bottom + gap + box.height <= window.innerHeight
        ? anchor.bottom + gap
        : anchor.top - box.height - gap,
    )}px`;
  };
  useEffect(() => {
    if (!open) return;
    position();
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
        onToggle={(event) => setOpen(event.newState === "open")}
      >
        {children}
      </div>
    </>
  );
}
