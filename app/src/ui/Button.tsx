import type { ComponentProps } from "react";
import { LoaderCircle } from "lucide-react";
type Props = ComponentProps<"button"> & {
  variant?: "default" | "primary" | "quiet" | "danger" | "link";
  size?: "compact" | "comfortable";
  pending?: boolean;
};
export function Button({
  variant = "default",
  size = "compact",
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
      className={["ui-button", `ui-button--${size}`, appearance, className]
        .filter(Boolean)
        .join(" ")}
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
