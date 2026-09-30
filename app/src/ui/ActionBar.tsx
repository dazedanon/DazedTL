import type { ReactNode } from "react";
export function ActionBar({
  feedback,
  children,
}: {
  feedback: ReactNode;
  children: ReactNode;
}) {
  return (
    <footer className="action-bar">
      {feedback}
      <div className="action-bar-actions">{children}</div>
    </footer>
  );
}
