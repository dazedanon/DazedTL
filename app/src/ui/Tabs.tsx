import { useRef, type ReactNode } from "react";
export interface Tab<T extends string> {
  id: T;
  label: ReactNode;
  disabled?: boolean;
}
export function Tabs<T extends string>({
  id,
  label,
  items,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  items: readonly Tab<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  const buttons = useRef(new Map<T, HTMLButtonElement>());
  const focusable = items.find((item) => item.id === value && !item.disabled) || items.find((item) => !item.disabled);
  return (
    <div role="tablist" aria-label={label} className="ui-tabs">
      {items.map((item) => (
        <button
          type="button"
          key={item.id}
          ref={(node) => {
            if (node) buttons.current.set(item.id, node);
            else buttons.current.delete(item.id);
          }}
          id={`${id}-tab-${item.id}`}
          role="tab"
          aria-selected={value === item.id}
          aria-controls={
            value === item.id ? `${id}-panel-${item.id}` : undefined
          }
          tabIndex={focusable?.id === item.id ? 0 : -1}
          disabled={disabled || item.disabled}
          onClick={() => onChange(item.id)}
          onKeyDown={(event) => {
            const enabled = items.filter((tab) => !tab.disabled);
            const index = enabled.findIndex((tab) => tab.id === item.id);
            const next =
              event.key === "ArrowRight"
                ? (index + 1) % enabled.length
                : event.key === "ArrowLeft"
                  ? (index + enabled.length - 1) % enabled.length
                  : event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? enabled.length - 1
                      : null;
            if (next === null || !enabled.length) return;
            event.preventDefault();
            const target = enabled[next].id;
            onChange(target);
            buttons.current.get(target)?.focus();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
export function TabPanel({
  id,
  value,
  children,
}: {
  id: string;
  value: string;
  children: ReactNode;
}) {
  return (
    <div
      role="tabpanel"
      id={`${id}-panel-${value}`}
      aria-labelledby={`${id}-tab-${value}`}
    >
      {children}
    </div>
  );
}
