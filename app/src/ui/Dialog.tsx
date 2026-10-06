import type { ComponentProps, ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "./Button";

/**
 * The top of a sized dialog: title, optional description and actions, and
 * its one close button. Spending reviews leave out `onClose` and offer
 * explicit choices in their footer instead.
 */
export function DialogHeader({
  title,
  description,
  actions,
  onClose,
  closeLabel = "Close",
  closeDisabled = false,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  onClose?: () => void;
  closeLabel?: string;
  closeDisabled?: boolean;
}) {
  return (
    <header className="dialog-header">
      <div className="dialog-heading">
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
      {onClose && (
        <Button
          variant="quiet"
          className="dialog-close"
          aria-label={closeLabel}
          title={closeLabel}
          disabled={closeDisabled}
          onClick={onClose}
        >
          <X size={18} aria-hidden="true" />
        </Button>
      )}
    </header>
  );
}

/** A dialog's scrolling content between its header and footer. */
export function DialogBody({
  className = "",
  ...props
}: ComponentProps<"div">) {
  return <div {...props} className={`dialog-body ${className}`} />;
}
