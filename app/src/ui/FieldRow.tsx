import type { ReactNode } from "react";
interface ControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
}
export function FieldRow({
  id,
  label,
  help,
  error,
  children,
  wide = false,
}: {
  id: string;
  label: string;
  help?: string;
  error?: string;
  children: (props: ControlProps) => ReactNode;
  wide?: boolean;
}) {
  const description =
    [help && `${id}-help`, error && `${id}-error`].filter(Boolean).join(" ") ||
    undefined;
  return (
    <div className="field-row">
      <label htmlFor={id}>{label}</label>
      <div className={`field-control${wide ? " field-control--wide" : ""}`}>
        {children({
          id,
          "aria-describedby": description,
          "aria-invalid": error ? true : undefined,
        })}
        {help && <small id={`${id}-help`}>{help}</small>}
        {error && (
          <small className="field-error" id={`${id}-error`} role="alert">
            {error}
          </small>
        )}
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
