import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleX,
  Contrast,
  LoaderCircle,
} from "lucide-react";

export type StatusKind =
  "done" | "active" | "partial" | "idle" | "warning" | "failed";

const icons = {
  done: CircleCheck,
  active: LoaderCircle,
  partial: Contrast,
  idle: CircleDashed,
  warning: CircleAlert,
  failed: CircleX,
};

/**
 * The one set of status marks: done, running, partly done, not started,
 * warning and failed. Text beside the mark names the state; pass `label`
 * only when the mark stands alone.
 */
export function StatusIcon({
  status,
  label,
  size = 16,
}: {
  status: StatusKind;
  label?: string;
  size?: number;
}) {
  const Icon = icons[status];
  return (
    <Icon
      size={size}
      className={`status-icon status-icon--${status}`}
      {...(label
        ? { role: "img", "aria-label": label }
        : { "aria-hidden": true })}
    />
  );
}
