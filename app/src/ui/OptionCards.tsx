import type { ReactNode } from "react";
import { Button } from "./Button";

export interface OptionCard<T extends string> {
  value: T;
  title: ReactNode;
  description: ReactNode;
  /** A short mark beside the title, such as "Recommended". */
  badge?: string;
  disabled?: boolean;
}

/** One choice among a few that each need a line of explanation. */
export function OptionCards<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled = false,
  autoFocus = false,
  className = "",
}: {
  label: string;
  value: T;
  options: readonly OptionCard<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  /** Focuses the chosen card when its Modal opens on this choice. */
  autoFocus?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`option-cards ${className}`.trim()}
      role="group"
      aria-label={label}
    >
      {options.map((option) => (
        <Button
          key={option.value}
          aria-pressed={value === option.value}
          data-autofocus={autoFocus && value === option.value ? "" : undefined}
          disabled={disabled || option.disabled}
          onClick={() => onChange(option.value)}
        >
          <strong>
            {option.title}
            {option.badge && <span className="badge">{option.badge}</span>}
          </strong>
          <small>{option.description}</small>
        </Button>
      ))}
    </div>
  );
}
