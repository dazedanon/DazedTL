import {
  CircleAlert,
  CircleArrowDown,
  CircleCheck,
  CircleDashed,
  CircleMinus,
  CircleX,
  Contrast,
  Eye,
  Hourglass,
  LoaderCircle,
  RotateCcw,
} from "lucide-react";

export type StatusKind =
  | "done"
  | "active"
  | "waiting"
  | "review"
  | "ready"
  | "outdated"
  | "skipped"
  | "partial"
  | "idle"
  | "warning"
  | "failed";

const icons = {
  done: CircleCheck,
  active: LoaderCircle,
  waiting: Hourglass,
  review: Eye,
  ready: CircleArrowDown,
  outdated: RotateCcw,
  skipped: CircleMinus,
  partial: Contrast,
  idle: CircleDashed,
  warning: CircleAlert,
  failed: CircleX,
};

/**
 * The one set of status marks. Work items use them through StatusMark and
 * the shared display states; other states, such as a connection check, may
 * use a mark directly. Text beside the mark names the state; pass `label`
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
