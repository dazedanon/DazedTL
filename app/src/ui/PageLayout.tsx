import type { ComponentProps, ReactNode, Ref } from "react";
export function PageLayout({
  variant = "document",
  className = "",
  ...props
}: ComponentProps<"section"> & { variant?: "document" | "editor" }) {
  return (
    <section
      {...props}
      className={`page-layout page-layout--${variant} ${className}`}
    />
  );
}
export function PageHeader({
  title,
  description,
  actions,
  divided = false,
  className = "",
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  divided?: boolean;
  className?: string;
}) {
  return (
    <header
      className={`page-header ${divided ? "page-header--divided" : ""} ${className}`}
    >
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions}
    </header>
  );
}
export function PageBody({
  className = "",
  ref,
  ...props
}: ComponentProps<"div"> & { ref?: Ref<HTMLDivElement> }) {
  return <div {...props} ref={ref} className={`page-body ${className}`} />;
}
