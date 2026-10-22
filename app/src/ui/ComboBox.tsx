import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentProps,
} from "react";
import { ChevronDown } from "lucide-react";
import { useOnChange } from "../state/useOnChange";

type Props = Omit<ComponentProps<"input">, "value" | "onChange" | "list"> & {
  value: string;
  options: readonly (
    | string
    | {
        value: string;
        label: string;
        description?: string;
        /** Colors the description for a status that needs attention. */
        tone?: "error" | "warning";
        searchText?: string;
      }
  )[];
  onChange: (value: string) => void;
  selectionOnly?: boolean;
};

/**
 * Editable suggestions, fixed choices, or searchable selection in a bounded
 * popup. The top-layer list scrolls within the available window height and
 * opens above the field when space below is limited, and follows the field
 * when the page moves it. It stands in for the
 * native datalist popup, so typed values and keyboard selection are kept
 * here; choice labels hide the automatic selection highlight (ui.css) while
 * still replacing on typing, and typed queries and editable text keep normal
 * selection.
 */
export function ComboBox({
  value,
  options,
  onChange,
  disabled,
  readOnly,
  selectionOnly = false,
  ...props
}: Props) {
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [query, setQuery] = useState<string | null>(null);
  const entries = options.map(
    (option): Exclude<Props["options"][number], string> =>
      typeof option === "string" ? { value: option, label: option } : option,
  );
  const search = (selectionOnly ? query || "" : value).toLowerCase();
  const matches = entries.filter(
    (option) =>
      readOnly ||
      showAll ||
      (option.searchText ?? `${option.label}\n${option.description || ""}`)
        .toLowerCase()
        .includes(search),
  );
  const activeIndex =
    active === null
      ? -1
      : matches.findIndex((option) => option.value === active);
  const expanded = open && !disabled && options.length > 0;

  function show(all = false) {
    setShowAll(all);
    setActive(
      (readOnly || selectionOnly) &&
        entries.some((option) => option.value === value)
        ? value
        : null,
    );
    setQuery(null);
    setOpen(true);
  }

  function close() {
    setOpen(false);
    setQuery(null);
  }

  function choose(option: string) {
    if (input.current?.matches(":disabled")) return;
    onChange(option);
    close();
    setActive(null);
    input.current?.focus({ preventScroll: true });
  }

  useOnChange(disabled, (now) => {
    if (!now) return;
    setOpen(false);
    setQuery(null);
  });

  useLayoutEffect(() => {
    if (!expanded) return;
    const popup = list.current!;
    const anchor = root.current!;
    popup.showPopover();
    const position = () => {
      const rect = anchor.getBoundingClientRect();
      const zoom = popup.currentCSSZoom || 1;
      const margin = 8 * zoom,
        gap = 4 * zoom;
      const below = Math.max(
        0,
        window.innerHeight - rect.bottom - margin - gap,
      );
      const above = Math.max(0, rect.top - margin - gap);
      const cap =
        parseFloat(getComputedStyle(document.documentElement).fontSize) *
        18 *
        zoom;
      const upwards =
        below < Math.min(cap, popup.scrollHeight * zoom) && above > below;
      // The list is at least as wide as its field and grows to read its
      // longest option on one line, within the window.
      popup.style.minWidth = `${Math.min(rect.width, window.innerWidth - margin * 2) / zoom}px`;
      popup.style.maxWidth = `min(32rem, ${(window.innerWidth - margin * 2) / zoom}px)`;
      const width = popup.getBoundingClientRect().width;
      popup.style.left = `${Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin)) / zoom}px`;
      popup.style.setProperty(
        "--combobox-available-height",
        `${(upwards ? above : below) / zoom}px`,
      );
      popup.style.top = `${(upwards ? rect.top - gap - popup.getBoundingClientRect().height : rect.bottom + gap) / zoom}px`;
    };
    const outside = (event: PointerEvent) => {
      if (!anchor.contains(event.target as Node)) close();
    };
    const scroll = (event: Event) => {
      if (!popup.contains(event.target as Node)) close();
    };
    position();
    // The field can move without resizing, such as a row appearing above it
    // after the list opened; the list follows it.
    let frame = 0;
    let placed = anchor.getBoundingClientRect();
    const follow = () => {
      const now = anchor.getBoundingClientRect();
      if (now.top !== placed.top || now.left !== placed.left) {
        placed = now;
        position();
      }
      frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    const resize = new ResizeObserver(position);
    resize.observe(anchor);
    resize.observe(popup);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", scroll, true);
    document.addEventListener("pointerdown", outside);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", scroll, true);
      document.removeEventListener("pointerdown", outside);
      popup.hidePopover();
    };
  }, [expanded, selectionOnly]);

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
        value={
          selectionOnly && query !== null
            ? query
            : readOnly || selectionOnly
              ? (entries.find((option) => option.value === value)?.label ??
                value)
              : value
        }
        readOnly={readOnly}
        disabled={disabled}
        data-choice-label={
          readOnly || (selectionOnly && query === null) || undefined
        }
        role="combobox"
        autoComplete="off"
        aria-autocomplete={readOnly ? "none" : "list"}
        aria-expanded={expanded}
        aria-controls={expanded ? listId : undefined}
        aria-activedescendant={
          expanded && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined
        }
        onFocus={(event) => {
          show();
          if (selectionOnly) event.currentTarget.select();
        }}
        onClick={(event) => {
          if (!expanded) show();
          if (selectionOnly && query === null) event.currentTarget.select();
        }}
        onBlur={close}
        onChange={(event) => {
          if (selectionOnly) {
            setQuery(event.target.value);
            setShowAll(false);
            setActive(null);
            setOpen(true);
          } else {
            onChange(event.target.value);
            show();
          }
        }}
        onPaste={(event) => {
          if (selectionOnly && query === null) event.currentTarget.select();
        }}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) return;
          // An edit of the shown label starts a new search, wherever the
          // caret is: a choice or a click can leave it inside the label.
          if (
            selectionOnly &&
            query === null &&
            (!(event.ctrlKey || event.metaKey) ||
              event.getModifierState("AltGraph")) &&
            (event.key.length === 1 ||
              ["Process", "Backspace", "Delete"].includes(event.key))
          )
            event.currentTarget.select();
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            const previous =
              !expanded && (readOnly || selectionOnly)
                ? matches.findIndex((option) => option.value === value)
                : activeIndex;
            const index =
              previous < 0
                ? event.key === "ArrowDown"
                  ? 0
                  : matches.length - 1
                : Math.max(
                    0,
                    Math.min(
                      matches.length - 1,
                      previous + (event.key === "ArrowDown" ? 1 : -1),
                    ),
                  );
            setActive(matches[index]?.value ?? null);
          } else if (
            expanded &&
            (event.key === "Enter" || (readOnly && event.key === " "))
          ) {
            // Choosing a suggestion must not also submit the containing form.
            event.preventDefault();
            if (activeIndex >= 0) choose(matches[activeIndex].value);
            else if (selectionOnly && matches.length === 1)
              choose(matches[0].value);
            else close();
          } else if (
            (readOnly || selectionOnly) &&
            (event.key === "Enter" || (readOnly && event.key === " "))
          ) {
            event.preventDefault();
            show(true);
          } else if (expanded && event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            close();
          } else if (event.key === "Tab") {
            close();
          }
        }}
      />
      {options.length > 0 && (
        <button
          type="button"
          className="combobox-toggle"
          tabIndex={-1}
          disabled={disabled}
          aria-label="Show suggestions"
          aria-controls={listId}
          aria-expanded={expanded}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            input.current?.focus({ preventScroll: true });
            if (expanded) close();
            else show(true);
          }}
        >
          <ChevronDown size={16} aria-hidden="true" />
        </button>
      )}
      {expanded && (
        <div
          ref={list}
          id={listId}
          popover="manual"
          role="listbox"
          className="combobox-list"
          aria-label="Suggestions"
          onMouseDown={(event) => event.preventDefault()}
        >
          {matches.map((option, index) => (
            <div
              key={option.value}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === activeIndex}
              className="combobox-option"
              onClick={() => choose(option.value)}
            >
              {option.label}
              {option.description && (
                <small
                  className="combobox-option-description"
                  data-tone={option.tone}
                >
                  {option.description}
                </small>
              )}
            </div>
          ))}
          {!matches.length && (
            <div className="combobox-empty" role="status">
              No matching suggestions.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
