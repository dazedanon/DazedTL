import type { ReactNode } from "react";

/**
 * An inline note beside the content it describes. Neutral notes read as
 * plain secondary text, so empty states do not look like problems.
 */
export function Notice({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "warning";
  children: ReactNode;
}) {
  return (
    <div
      className={`notice notice--${tone}`}
      role={tone === "warning" ? "status" : undefined}
    >
      {children}
    </div>
  );
}
