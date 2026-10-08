import type { ReactNode } from "react";
import { HelpPopover } from "./HelpPopover";
interface ControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
}
export function FieldRow({
  id,
  label,
  help,
  helpDisplay = "text",
  error,
  children,
  wide = false,
}: {
  id: string;
  label: string;
  help?: string;
  helpDisplay?: "text" | "popover";
  error?: string;
  children: (props: ControlProps) => ReactNode;
  wide?: boolean;
}) {
  const description =
    [help && `${id}-help`, error && `${id}-error`].filter(Boolean).join(" ") ||
    undefined;
  return (
    <div className="field-row">
      {help && helpDisplay === "popover" ? (
        <div className="field-label field-label--help">
          <label htmlFor={id}>{label}</label>
          <HelpPopover id={`${id}-help`} label={label}>
            {help}
          </HelpPopover>
        </div>
      ) : (
        <label htmlFor={id}>{label}</label>
      )}
      <div className={`field-control${wide ? " field-control--wide" : ""}`}>
        {children({
          id,
          "aria-describedby": description,
          "aria-invalid": error ? true : undefined,
        })}
        {help && helpDisplay === "text" && (
          <small id={`${id}-help`}>{help}</small>
        )}
        {error && (
          <small className="field-error" id={`${id}-error`} role="alert">
            {error}
          </small>
        )}
      </div>
    </div>
  );
}
/** A checkbox before its label, so the two read as one choice. */
export function CheckField({
  id,
  label,
  help,
  checked,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  help?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="check-field">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-describedby={help ? `${id}-help` : undefined}
        onChange={(event) => onChange(event.target.checked)}
      />
      <label htmlFor={id}>{label}</label>
      {help && (
        <HelpPopover id={`${id}-help`} label={label}>
          {help}
        </HelpPopover>
      )}
    </div>
  );
}
/**
 * Related checkboxes under one label, laid out like a field row: the label
 * above them on pages and in the label column in dialogs. Choices that read
 * as one list wrap into columns; `stacked` keeps one choice per line.
 */
export function CheckGroup({
  id,
  label,
  help,
  stacked = false,
  children,
}: {
  id: string;
  label: string;
  help?: string;
  stacked?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className="field-row"
      role="group"
      aria-labelledby={`${id}-label`}
      aria-describedby={help ? `${id}-help` : undefined}
    >
      <span className="field-label" id={`${id}-label`}>
        {label}
      </span>
      <div className="field-control">
        <div className={`check-group${stacked ? " check-group--stacked" : ""}`}>
          {children}
        </div>
        {help && <small id={`${id}-help`}>{help}</small>}
      </div>
    </div>
  );
}
export function DetailRow({
  label,
  className = "",
  valueClassName,
  children,
}: {
  label: string;
  className?: string;
  valueClassName?: string;
  children: ReactNode;
}) {
  return (
    <div className={`summary-row ${className}`}>
      <dt>{label}</dt>
      <dd className={valueClassName}>{children}</dd>
    </div>
  );
}
