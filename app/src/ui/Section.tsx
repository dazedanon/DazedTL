import { useId, type ReactNode } from "react";
export function Section({
  title,
  hint,
  id,
  className = "",
  children,
}: {
  title: ReactNode;
  hint?: ReactNode;
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  const generated = useId();
  const heading = id || generated;
  return (
    <section className={`ui-section ${className}`} aria-labelledby={heading}>
      <h2 id={heading}>
        {title}
        {hint && <span>{hint}</span>}
      </h2>
      {children}
    </section>
  );
}
