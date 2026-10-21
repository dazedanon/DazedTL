import type { ComponentProps } from "react";
import { LoaderCircle } from "lucide-react";
type Props = ComponentProps<"button"> & {
  /**
   * `primary` is a screen's one main action. `quiet` belongs in toolbars,
   * headers and footers, where its padding is the hit area; `link` serves
   * tertiary actions inside running content, where its label lines up with
   * the surrounding text.
   */
  variant?: "default" | "primary" | "quiet" | "danger" | "link";
  pending?: boolean;
};
export function Button({
  variant = "default",
  pending = false,
  disabled,
  type = "button",
  className = "",
  children,
  ...props
}: Props) {
  const appearance =
    variant === "default" ? "" : variant === "link" ? "link-button" : variant;
  return (
    <button
      {...props}
      type={type}
      className={["ui-button", appearance, className].filter(Boolean).join(" ")}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
    >
      {pending && (
        <LoaderCircle
          size={14}
          className="ui-button-spinner"
          aria-hidden="true"
        />
      )}
      {children}
    </button>
  );
}
