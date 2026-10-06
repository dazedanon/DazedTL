import type { ReactNode } from "react";
import { Button } from "./Button";

export interface Segment<T extends string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
  /** Explains a disabled choice, or what the choice implies. */
  title?: string;
}

/** One choice among a few, drawn as one joined control of pressed buttons. */
export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled = false,
  className = "",
}: {
  label: string;
  value: T;
  options: readonly Segment<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`segmented-control ${className}`.trim()}
      role="group"
      aria-label={label}
    >
      {options.map((option) => (
        <Button
          key={option.value}
          aria-pressed={value === option.value}
          disabled={disabled || option.disabled}
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}
