import type { ReactNode } from "react";

/**
 * An inline note beside the content it describes. Neutral notes read as
 * plain secondary text, so empty states do not look like problems. Warnings
 * get the warning edge and carry their way forward beside them.
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

/**
 * The problems that refuse work on the whole game, such as a game folder
 * left mid-update, as the one amber notice every screen shows them with.
 */
export function GameWarnings({ warnings }: { warnings: readonly string[] }) {
  return warnings.map((warning) => (
    <Notice key={warning} tone="warning">
      <span>{warning}</span>
    </Notice>
  ));
}
