import { useEffect, useId, useLayoutEffect, useRef, useState, type ComponentProps } from "react";
import { ChevronDown } from "lucide-react";

type Props = Omit<ComponentProps<"input">, "value" | "onChange" | "list"> & {
  value: string;
  options: readonly (string | { value: string; label: string })[];
  onChange: (value: string) => void;
};

/** Editable suggestions or read-only selection in a bounded top-layer popup. */
export function ComboBox({ value, options, onChange, disabled, readOnly, ...props }: Props) {
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const entries = options.map(option => typeof option === "string" ? { value: option, label: option } : option);
  const matches = entries.filter(option => readOnly || showAll || option.label.toLowerCase().includes(value.toLowerCase()));
  const activeIndex = active === null ? -1 : matches.findIndex(option => option.value === active);
  const expanded = open && !disabled && options.length > 0;

  function show(all = false) {
    setShowAll(all);
    setActive(readOnly && entries.some(option => option.value === value) ? value : null);
    setOpen(true);
  }

  function choose(option: string) {
    if (input.current?.matches(":disabled")) return;
    onChange(option);
    setOpen(false);
    setActive(null);
    input.current?.focus({ preventScroll: true });
  }

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useLayoutEffect(() => {
    if (!expanded) return;
    const popup = list.current!;
    const anchor = root.current!;
    popup.showPopover();
    const position = () => {
      const rect = anchor.getBoundingClientRect();
      const zoom = popup.currentCSSZoom || 1;
      const margin = 8 * zoom, gap = 4 * zoom;
      const below = Math.max(0, window.innerHeight - rect.bottom - margin - gap);
      const above = Math.max(0, rect.top - margin - gap);
      const cap = parseFloat(getComputedStyle(document.documentElement).fontSize) * 18 * zoom;
      const upwards = below < Math.min(cap, popup.scrollHeight * zoom) && above > below;
      const width = Math.min(rect.width, window.innerWidth - margin * 2);
      popup.style.width = `${width / zoom}px`;
      popup.style.left = `${Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin)) / zoom}px`;
      popup.style.setProperty("--combobox-available-height", `${(upwards ? above : below) / zoom}px`);
      popup.style.top = `${(upwards ? rect.top - gap - popup.getBoundingClientRect().height : rect.bottom + gap) / zoom}px`;
    };
    const outside = (event: PointerEvent) => {
      if (!anchor.contains(event.target as Node)) setOpen(false);
    };
    const scroll = (event: Event) => {
      if (!popup.contains(event.target as Node)) setOpen(false);
    };
    position();
    const resize = new ResizeObserver(position);
    resize.observe(anchor);
    resize.observe(popup);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", scroll, true);
    document.addEventListener("pointerdown", outside);
    return () => {
      resize.disconnect();
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", scroll, true);
      document.removeEventListener("pointerdown", outside);
      popup.hidePopover();
    };
  }, [expanded]);

  useLayoutEffect(() => {
    if (expanded && activeIndex >= 0) {
      list.current?.children[activeIndex]?.scrollIntoView({ block: "nearest" });
    }
  }, [expanded, activeIndex]);

  return (
    <div ref={root} className="combobox">
      <input
        {...props}
        ref={input}
        value={readOnly ? entries.find(option => option.value === value)?.label ?? value : value}
        readOnly={readOnly}
        disabled={disabled}
        role="combobox"
        autoComplete="off"
        aria-autocomplete={readOnly ? "none" : "list"}
        aria-expanded={expanded}
        aria-controls={expanded ? listId : undefined}
        aria-activedescendant={expanded && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
        onFocus={() => show()}
        onClick={() => { if (!expanded) show(); }}
        onBlur={() => setOpen(false)}
        onChange={event => { onChange(event.target.value); show(); }}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            const index = !expanded || activeIndex < 0
              ? event.key === "ArrowDown" ? 0 : matches.length - 1
              : Math.max(0, Math.min(matches.length - 1, activeIndex + (event.key === "ArrowDown" ? 1 : -1)));
            setActive(matches[index]?.value ?? null);
          } else if (expanded && (event.key === "Enter" || readOnly && event.key === " ")) {
            // Choosing a suggestion must not also submit the containing form.
            event.preventDefault();
            if (activeIndex >= 0) choose(matches[activeIndex].value);
            else setOpen(false);
          } else if (readOnly && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            show(true);
          } else if (expanded && event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
          } else if (event.key === "Tab") {
            setOpen(false);
          }
        }}
      />
      {options.length > 0 && (
        <button type="button" className="combobox-toggle" tabIndex={-1} disabled={disabled}
          aria-label="Show suggestions" aria-controls={listId} aria-expanded={expanded}
          onMouseDown={event => event.preventDefault()}
          onClick={() => {
            input.current?.focus({ preventScroll: true });
            if (expanded) setOpen(false);
            else show(true);
          }}>
          <ChevronDown size={16} aria-hidden="true" />
        </button>
      )}
      {expanded && (
        <div ref={list} id={listId} popover="manual" role="listbox" className="combobox-list"
          aria-label="Suggestions" onMouseDown={event => event.preventDefault()}>
          {matches.map((option, index) => (
            <div key={option.value} id={`${listId}-${index}`} role="option"
              aria-selected={index === activeIndex} className="combobox-option"
              onClick={() => choose(option.value)}>{option.label}</div>
          ))}
          {!matches.length && <div className="combobox-empty" role="status">No matching suggestions.</div>}
        </div>
      )}
    </div>
  );
}
