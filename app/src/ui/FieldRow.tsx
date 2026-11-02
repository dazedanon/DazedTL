import type { ReactNode } from "react";
import { GuideLink } from "./GuideLink";
import type { GuideSection } from "./guideSections";
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
  guide,
  note,
  error,
  children,
  wide = false,
}: {
  id: string;
  label: string;
  help?: string;
  helpDisplay?: "text" | "popover";
  /** The guide's section on the field, linked from its help. */
  guide?: GuideSection;
  /** A quiet line under the help, such as where a value comes from. */
  note?: string;
  error?: string;
  children: (props: ControlProps) => ReactNode;
  wide?: boolean;
}) {
  const description =
    [help && `${id}-help`, note && `${id}-note`, error && `${id}-error`]
      .filter(Boolean)
      .join(" ") || undefined;
  return (
    <div className="field-row">
      {help && helpDisplay === "popover" ? (
        <div className="field-label field-label--help">
          <label htmlFor={id}>{label}</label>
          <HelpPopover id={`${id}-help`} label={label} guide={guide}>
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
          <small id={`${id}-help`}>
            {help}
            {guide && (
              <>
                {" "}
                <GuideLink section={guide} />
              </>
            )}
          </small>
        )}
        {note && <small id={`${id}-note`}>{note}</small>}
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
  description,
  checked,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  help?: string;
  /** What the choice does, shown under its label. */
  description?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  const describedBy =
    [help && `${id}-help`, description && `${id}-description`]
      .filter(Boolean)
      .join(" ") || undefined;
  const name = (
    <>
      <label htmlFor={id}>{label}</label>
      {help && (
        <HelpPopover id={`${id}-help`} label={label}>
          {help}
        </HelpPopover>
      )}
    </>
  );
  return (
    <div
      className={`check-field${description ? " check-field--described" : ""}`}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.checked)}
      />
      {description ? (
        <>
          <span className="check-field-name">{name}</span>
          <small id={`${id}-description`}>{description}</small>
        </>
      ) : (
        name
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
