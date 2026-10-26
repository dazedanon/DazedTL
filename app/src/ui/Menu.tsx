import {
  createContext,
  useContext,
  useId,
  useLayoutEffect,
  useRef,
  type ComponentProps,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Button } from "./Button";
import { placeOnOpen, placePopover } from "./popoverPlacement";
import { useRefocus } from "./useRefocus";

const MenuContext = createContext<{
  close: () => void;
  /** Arms the list to refocus if this item's row leaves it. */
  refocus: (item: HTMLElement | null) => void;
}>({ close: () => {}, refocus: () => {} });

/** Centers the current item, such as the chosen model, in a long open list. */
const revealCurrent = (popup: HTMLElement | null) => {
  const item = popup?.querySelector<HTMLElement>(
    "[role=menuitem][aria-current]",
  );
  if (popup && item)
    popup.scrollTop =
      item.offsetTop - (popup.clientHeight - item.offsetHeight) / 2;
};

/**
 * A button that opens a list of actions in the top layer. The list closes on
 * a choice, Escape or a click elsewhere, and arrow keys move between items.
 */
export function Menu({
  trigger,
  label,
  align = "end",
  onOpen,
  children,
  ...button
}: Omit<ComponentProps<typeof Button>, "children" | "popoverTarget"> & {
  trigger: ReactNode;
  /** Names the list for assistive technology. */
  label: string;
  align?: "start" | "end";
  /** Loads items that are only needed while the list is open. */
  onOpen?: () => void;
  children: ReactNode;
}) {
  const id = useId();
  const anchor = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const items = () => [
    ...(list.current?.querySelectorAll<HTMLButtonElement>(
      "[role=menuitem]:not(:disabled)",
    ) || []),
  ];
  const refocus = useRefocus(items);
  const position = () => {
    if (list.current && anchor.current)
      placePopover(list.current, anchor.current, { align, fit: true });
  };
  const search = () =>
    list.current?.querySelector<HTMLInputElement>("[data-menu-search]");
  const keys = (event: KeyboardEvent) => {
    const all = items();
    // Typing stays in the search field; Down moves into its matches and Up
    // from the first match returns to it.
    if (document.activeElement === search()) {
      if (event.key !== "ArrowDown" || !all.length) return;
      event.preventDefault();
      all[0].focus();
      return;
    }
    const index = all.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowUp" && index === 0 && search()) {
      event.preventDefault();
      search()!.focus();
      return;
    }
    const next =
      event.key === "ArrowDown"
        ? (index + 1) % all.length
        : event.key === "ArrowUp"
          ? (index - 1 + all.length) % all.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? all.length - 1
              : null;
    if (next === null || !all.length) return;
    event.preventDefault();
    all[next].focus();
  };
  return (
    <MenuContext.Provider
      value={{ close: () => list.current?.hidePopover(), refocus }}
    >
      <Button {...button} ref={anchor} popoverTarget={id} aria-haspopup="menu">
        {trigger}
      </Button>
      <div
        ref={list}
        id={id}
        popover="auto"
        role="menu"
        aria-label={label}
        className="menu-list"
        onKeyDown={keys}
        onBeforeToggle={(event) => placeOnOpen(event, position)}
        onToggle={(event) => {
          anchor.current?.setAttribute(
            "aria-expanded",
            String(event.newState === "open"),
          );
          if (event.newState !== "open") {
            refocus(null);
            // Return focus to the trigger unless a choice moved it elsewhere.
            if (
              document.activeElement === document.body ||
              list.current?.contains(document.activeElement)
            )
              anchor.current?.focus({ preventScroll: true });
            return;
          }
          onOpen?.();
          revealCurrent(list.current);
          // onOpen may reset a filter, which renders after this event.
          requestAnimationFrame(() => revealCurrent(list.current));
          (
            search() ||
            items().find((item) => item.hasAttribute("aria-current")) ||
            items()[0]
          )?.focus({ preventScroll: true });
        }}
      >
        {children}
      </div>
    </MenuContext.Provider>
  );
}

export function MenuItem({
  onSelect,
  current = false,
  keepOpen = false,
  description,
  children,
  ...button
}: Omit<ComponentProps<"button">, "onClick" | "role"> & {
  onSelect: () => void;
  /** A line under the item: what it does, or why it is unavailable. */
  description?: ReactNode;
  /** Marks the item that matches the present state, such as the open project. */
  current?: boolean;
  /** Leaves the list open, such as for an item that removes its own row;
      focus then moves to the item taking its place. */
  keepOpen?: boolean;
}) {
  const { close, refocus } = useContext(MenuContext);
  const node = useRef<HTMLButtonElement>(null);
  // Items that load after the list opens, such as models, reveal themselves.
  useLayoutEffect(() => {
    if (current) revealCurrent(node.current?.closest(":popover-open") ?? null);
  }, [current]);
  return (
    <button
      type="button"
      {...button}
      ref={node}
      role="menuitem"
      aria-current={current || undefined}
      className={`menu-item ${description ? "menu-item--described" : ""} ${button.className || ""}`}
      onClick={(event) => {
        if (keepOpen) refocus(event.currentTarget);
        else close();
        onSelect();
      }}
    >
      {description ? (
        <>
          <span>{children}</span>
          <small className="menu-item-description">{description}</small>
        </>
      ) : (
        children
      )}
    </button>
  );
}

/** Filters a long menu's items; the menu focuses it when opened, including
    when items load after opening. Enter submits the typed value when the
    menu accepts one. */
export function MenuSearch({
  value,
  onChange,
  label,
  placeholder = "Search…",
  onSubmit,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
  onSubmit?: () => void;
}) {
  const { close } = useContext(MenuContext);
  const input = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => {
    if (input.current?.closest(":popover-open")) input.current.focus();
  }, []);
  return (
    <input
      ref={input}
      type="search"
      data-menu-search
      className="menu-search"
      aria-label={label}
      placeholder={placeholder}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if (event.key !== "Enter" || !onSubmit || !value.trim()) return;
        event.preventDefault();
        close();
        onSubmit();
      }}
    />
  );
}

export const MenuSeparator = () => (
  <div className="menu-separator" role="separator" />
);
